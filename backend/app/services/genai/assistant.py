"""
The assistant — FR-K-01 to FR-K-14.

Four capabilities, all assistive. None of them decides anything:

  1. Natural-language order entry   FR-K-01, FR-K-02
  2. Portfolio and trade questions  FR-K-03
  3. Performance commentary         FR-K-05
  4. Exception triage               FR-K-08

Data handling: prompts are built from figures already computed by the
platform. The model never queries the database and never sees client names
or account numbers — only an internal reference — FR-K-13.
"""
import re
import uuid
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.exception import AuditLog, TradingException
from app.models.instrument import Instrument
from app.models.order import Order, OrderSide, OrderType, TimeInForce
from app.models.trade import Trade
from app.services.genai.client import build_client, GenAIResult
from app.services.portfolio_engine import PortfolioEngine
from app.services.order_service import CommandParser


def _d(v, places=2):
    try:
        return f"{float(v):,.{places}f}"
    except (TypeError, ValueError):
        return "—"


class Assistant:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = build_client()
        self.portfolio = PortfolioEngine(db)

    # ── Audit — FR-K-09 ───────────────────────────────────────────────────

    def _log(self, user_id: str, feature: str, prompt: str, result: GenAIResult):
        """Every interaction is logged: prompt, response, model, provenance."""
        self.db.add(AuditLog(
            id=str(uuid.uuid4()),
            actor_type="USER",
            actor_id=user_id,
            action="GENAI_INTERACTION",
            entity_type="GENAI",
            reason_code=result.guardrail,
            detail={
                "feature": feature,
                "prompt": prompt[:2000],
                "response": result.text[:2000],
                "provider": result.provider,
                "model": result.model,
                "degraded": result.degraded,
                "latency_ms": result.latency_ms,
            },
        ))

    # ── 1. Natural-language order entry — FR-K-01, FR-K-02 ────────────────

    async def parse_order(self, text: str, user_id: str) -> dict:
        """
        Turn plain English into a structured order.

        Returns the parsed order for confirmation. It is NEVER submitted from
        here — FR-K-02. The caller must send it through the normal order path
        only after the user has explicitly confirmed.
        """
        instruments = await self._instrument_list()
        tickers = ", ".join(i.id for i in instruments)
        names = "; ".join(f"{i.id}={i.name}" for i in instruments)

        # Deterministic fallback: try the command grammar directly
        fb_req, fb_err = CommandParser.parse(text)
        fallback = {
            "understood": fb_req is not None,
            "side": fb_req.side.value if fb_req else None,
            "instrument_id": fb_req.instrument_id if fb_req else None,
            "quantity": str(fb_req.quantity) if fb_req else None,
            "order_type": fb_req.order_type.value if fb_req else "MARKET",
            "price": str(fb_req.price) if (fb_req and fb_req.price) else None,
            "time_in_force": fb_req.time_in_force.value if fb_req else "DAY",
            "clarification": None if fb_req else (
                "Could not read that as an order. Try the command form, "
                "for example: BUY 100 AAPL @MKT"
            ),
        }

        system = (
            "You convert a trader's plain-English instruction into a structured "
            "equity order for an execution platform.\n"
            f"Tradable instruments: {tickers}\n"
            f"Company names: {names}\n\n"
            "Return exactly these keys:\n"
            '  understood (bool), side ("BUY"|"SELL"|null), instrument_id (ticker|null),\n'
            '  quantity (string number|null), order_type ("MARKET"|"LIMIT"),\n'
            '  price (string number|null), time_in_force ("DAY"|"GTC"|"IOC"|"FOK"),\n'
            "  clarification (string|null)\n\n"
            "Rules:\n"
            "- Resolve company names to tickers (Apple -> AAPL).\n"
            "- If anything is ambiguous or missing, set understood=false and put a "
            "specific question in clarification. Never guess a quantity, a side or "
            "an instrument.\n"
            "- If no price is stated, order_type is MARKET and price is null.\n"
            "- Never invent a ticker that is not in the list above."
        )

        parsed, result = self.ai.generate_json(system, text, fallback=fallback)
        self._log(user_id, "parse_order", text, result)

        # Validate the model's output against reality before showing it
        valid_tickers = {i.id for i in instruments}
        if parsed.get("instrument_id") and parsed["instrument_id"] not in valid_tickers:
            parsed = {
                **parsed,
                "understood": False,
                "clarification": (
                    f"'{parsed['instrument_id']}' is not tradable here. "
                    f"Available: {tickers}"
                ),
            }
        if parsed.get("understood"):
            try:
                if Decimal(str(parsed.get("quantity") or 0)) <= 0:
                    parsed["understood"] = False
                    parsed["clarification"] = "How many shares?"
            except Exception:
                parsed["understood"] = False
                parsed["clarification"] = "How many shares?"

        return {
            "input": text,
            "parsed": parsed,
            "requires_confirmation": True,   # FR-K-02 — always
            "submitted": False,
            "provenance": result.provenance,
        }

    # ── 2. Questions over your own data — FR-K-03 ─────────────────────────

    async def ask(self, question: str, account: Account, user_id: str,
                  is_paper: bool = False) -> dict:
        """
        Answer a question using figures the platform has already computed.
        The model receives a snapshot, never database access.
        """
        snapshot = await self._snapshot(account, is_paper)

        system = (
            "You answer questions about one trading account, using only the data "
            "given to you.\n\n"
            "Rules:\n"
            "- Use only the figures provided. Never estimate, extrapolate or invent "
            "a number. If the data does not contain the answer, say so plainly.\n"
            "- No investment advice, no price predictions, no recommendations.\n"
            "- Be brief and concrete. Quote the actual figures.\n"
            "- Plain sentences. No markdown headings, no bullet lists unless the "
            "answer is genuinely a list."
        )
        user = f"Account data:\n{json.dumps(snapshot, indent=1)}\n\nQuestion: {question}"

        fallback = self._fallback_answer(question, snapshot)
        result = self.ai.generate(system, user, fallback=fallback, max_tokens=600)
        self._log(user_id, "ask", question, result)

        return {
            "question": question,
            "answer": result.text,
            "provenance": result.provenance,
            "data_used": snapshot,
        }

    # ── 3. Performance commentary — FR-K-05 ───────────────────────────────

    async def commentary(self, account: Account, user_id: str,
                         is_paper: bool = False) -> dict:
        snapshot = await self._snapshot(account, is_paper)

        system = (
            "You write a short performance note for the holder of a trading "
            "account.\n\n"
            "Rules:\n"
            "- Three or four sentences. No headings, no bullets.\n"
            "- Every number you use must appear in the data given. Never introduce "
            "a figure that is not there.\n"
            "- Describe what happened and what drove it. Do not suggest what to do "
            "next, and do not forecast.\n"
            "- Neutral, factual tone. This is a statement note, not marketing."
        )
        user = json.dumps(snapshot, indent=1)

        fallback = self._fallback_commentary(snapshot)
        result = self.ai.generate(system, user, fallback=fallback, max_tokens=400)
        self._log(user_id, "commentary", "portfolio commentary", result)

        return {
            "commentary": result.text,
            "provenance": result.provenance,
            "as_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── 4. Exception triage — FR-K-08 ─────────────────────────────────────

    async def triage(self, exception_id: str, user_id: str) -> dict:
        result_row = await self.db.execute(
            select(TradingException).where(TradingException.id == exception_id)
        )
        exc = result_row.scalar_one_or_none()
        if exc is None:
            return {"error": "Exception not found"}

        payload = {
            "code": str(exc.code),
            "severity": str(exc.severity),
            "entity_type": exc.entity_type,
            "description": exc.description,
            "detail": exc.detail,
            "raised_at": exc.raised_at.isoformat() if exc.raised_at else None,
        }

        system = (
            "You help an operations analyst triage a break in a trade processing "
            "platform.\n\n"
            "Exception codes: EX-REF reference data · EX-VAL validation · "
            "EX-RSK risk breach · EX-CMP compliance · EX-EXE execution · "
            "EX-FIL fill mismatch · EX-ALC allocation · EX-SET settlement · "
            "EX-REC reconciliation · EX-SYS system · EX-AI model\n\n"
            "Give: one sentence on the likely cause, then two or three concrete "
            "checks the analyst should make, then what to do if those confirm it.\n"
            "This is advisory. The analyst decides and records the action. Do not "
            "state that anything has been fixed."
        )

        fallback = (
            f"{payload['code']} raised at {payload['severity']} severity. "
            "Open the related record, confirm the reported condition still holds, "
            "correct the underlying data or limit, then resubmit and record the "
            "reason for closure."
        )
        result = self.ai.generate(system, json.dumps(payload, indent=1),
                                  fallback=fallback, max_tokens=400)
        self._log(user_id, "triage", f"exception {exception_id}", result)

        return {
            "exception_id": exception_id,
            "code": payload["code"],
            "suggestion": result.text,
            "advisory_only": True,   # FR-K-08 — analyst must confirm any action
            "provenance": result.provenance,
        }

    # ── Data assembly ─────────────────────────────────────────────────────

    async def _instrument_list(self) -> list[Instrument]:
        r = await self.db.execute(select(Instrument).order_by(Instrument.id))
        return list(r.scalars().all())

    async def _snapshot(self, account: Account, is_paper: bool) -> dict:
        """
        Everything the model is allowed to see. Note what is absent:
        no client name, no account number, no user identity — FR-K-13.
        """
        summary = await self.portfolio.get_summary(account, is_paper)

        trades_r = await self.db.execute(
            select(Trade)
            .where(Trade.account_id == account.id)
            .where(Trade.is_paper.is_(is_paper))
            .order_by(desc(Trade.trade_date)).limit(20)
        )
        trades = list(trades_r.scalars().all())

        orders_r = await self.db.execute(
            select(Order)
            .where(Order.account_id == account.id)
            .where(Order.is_paper.is_(is_paper))
            .order_by(desc(Order.received_at)).limit(20)
        )
        orders = list(orders_r.scalars().all())

        positions = sorted(
            summary.positions, key=lambda p: float(p.unrealised_pnl), reverse=True
        )

        return {
            "account_reference": f"ACC-{account.id[:8]}",   # no real identifiers
            "mode": "paper" if is_paper else "live",
            "currency": account.base_currency,
            "valuation": {
                "total_value": _d(summary.total_value),
                "positions_value": _d(summary.positions_value),
                "cost_basis": _d(summary.total_cost_basis),
                "cash_settled": _d(summary.cash_settled),
                "cash_unsettled": _d(summary.cash_unsettled),
                "buying_power": _d(summary.cash_settled),
            },
            "pnl": {
                "unrealised": _d(summary.unrealised_pnl),
                "unrealised_pct": _d(summary.unrealised_pnl_pct),
                "realised": _d(summary.realised_pnl),
            },
            "position_count": summary.position_count,
            "positions": [
                {
                    "instrument": p.instrument_id,
                    "quantity": _d(p.quantity, 0),
                    "avg_cost": _d(p.avg_cost),
                    "last_price": _d(p.last_price) if p.last_price else None,
                    "market_value": _d(p.market_value),
                    "unrealised_pnl": _d(p.unrealised_pnl),
                    "unrealised_pct": _d(p.unrealised_pnl_pct),
                    "realised_pnl": _d(p.realised_pnl),
                }
                for p in positions
            ],
            "best_position": positions[0].instrument_id if positions else None,
            "worst_position": positions[-1].instrument_id if positions else None,
            "recent_trades": [
                {
                    "instrument": t.instrument_id, "side": t.side,
                    "quantity": _d(t.quantity, 0), "price": _d(t.price),
                    "charges": _d(Decimal(str(t.commission)) + Decimal(str(t.exchange_fee)) + Decimal(str(t.tax))),
                    "net": _d(t.net_consideration),
                    "settles": t.settlement_date,
                    "settlement_status": str(t.settlement_status),
                    "date": t.trade_date.isoformat() if t.trade_date else None,
                }
                for t in trades
            ],
            "recent_orders": [
                {
                    "instrument": o.instrument_id, "side": str(o.side),
                    "quantity": _d(o.quantity, 0), "state": str(o.state),
                    "rejected_because": o.reject_reason,
                }
                for o in orders
            ],
            "rejected_order_count": sum(1 for o in orders if str(o.state) == "REJECTED"),
        }

    # ── Deterministic fallbacks — FR-K-10 ─────────────────────────────────

    @staticmethod
    def _fallback_answer(question: str, snap: dict) -> str:
        """
        Rule-based answers so the feature still works with no model.
        Deliberately narrow: better to say "I can't answer that here" than
        to guess.
        """
        q = (question or "").lower()
        v, p = snap["valuation"], snap["pnl"]

        if any(k in q for k in ["worst", "losing", "loser", "down the most"]):
            if not snap["positions"]:
                return "There are no positions on this account."
            w = snap["positions"][-1]
            return (f"{w['instrument']} is the weakest holding, at "
                    f"{w['unrealised_pnl']} ({w['unrealised_pct']}%) unrealised.")

        if any(k in q for k in ["best", "winner", "up the most", "performing"]):
            if not snap["positions"]:
                return "There are no positions on this account."
            b = snap["positions"][0]
            return (f"{b['instrument']} is the strongest holding, at "
                    f"{b['unrealised_pnl']} ({b['unrealised_pct']}%) unrealised.")

        if any(k in q for k in ["cash", "buying power", "afford"]):
            return (f"Buying power is {v['buying_power']} {snap['currency']}, "
                    f"with {v['cash_unsettled']} still unsettled.")

        if any(k in q for k in ["p&l", "pnl", "profit", "loss", "made", "lost"]):
            return (f"Unrealised P&L is {p['unrealised']} ({p['unrealised_pct']}%). "
                    f"Realised P&L is {p['realised']}.")

        if any(k in q for k in ["hold", "position", "own", "what do i have"]):
            if not snap["positions"]:
                return "There are no open positions on this account."
            return "Holdings: " + "; ".join(
                f"{x['quantity']} {x['instrument']} at {x['market_value']}"
                for x in snap["positions"]
            )

        if any(k in q for k in ["reject", "failed", "why did"]):
            n = snap["rejected_order_count"]
            if n == 0:
                return "No orders have been rejected on this account recently."
            reasons = {o["rejected_because"] for o in snap["recent_orders"]
                       if o.get("rejected_because")}
            return (f"{n} recent order(s) were rejected. Reasons seen: "
                    + ", ".join(sorted(r for r in reasons if r)) + ".")

        if any(k in q for k in ["trade", "bought", "sold", "history"]):
            if not snap["recent_trades"]:
                return "No trades have been executed on this account."
            t = snap["recent_trades"][0]
            return (f"Most recent trade: {t['side']} {t['quantity']} "
                    f"{t['instrument']} at {t['price']}, settling {t['settles']}.")

        return (
            f"Without a language model connected I can only answer set questions. "
            f"This account is worth {v['total_value']} with {p['unrealised']} "
            f"unrealised P&L across {snap['position_count']} position(s). "
            f"Try asking about holdings, cash, P&L, rejected orders or recent trades."
        )

    @staticmethod
    def _fallback_commentary(snap: dict) -> str:
        v, p = snap["valuation"], snap["pnl"]
        if snap["position_count"] == 0:
            return (f"The account holds no positions. Buying power stands at "
                    f"{v['buying_power']} {snap['currency']}.")
        best = snap["positions"][0]
        worst = snap["positions"][-1]
        line = (
            f"The account is valued at {v['total_value']} {snap['currency']}, "
            f"across {snap['position_count']} position(s) with "
            f"{v['buying_power']} in buying power. "
            f"Unrealised P&L stands at {p['unrealised']} ({p['unrealised_pct']}%), "
            f"with realised P&L of {p['realised']}. "
        )
        if best["instrument"] != worst["instrument"]:
            line += (f"{best['instrument']} is the largest contributor at "
                     f"{best['unrealised_pnl']}, while {worst['instrument']} "
                     f"sits at {worst['unrealised_pnl']}.")
        else:
            line += (f"{best['instrument']} is the only holding, at "
                     f"{best['unrealised_pnl']} unrealised.")
        return line
