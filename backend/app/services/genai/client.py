"""
GenAI provider abstraction — FR-K-01 to FR-K-14.

Three providers, selected by GENAI_PROVIDER in .env:
    gemini     — Google Gemini (free tier)
    anthropic  — Anthropic Claude
    none       — deterministic fallbacks only

Switching provider is a configuration change, not a code change. No other
module in the platform imports an LLM client; everything goes through here.

FR-K-10 (graceful degradation): every method returns a usable result even
when no provider is configured, when the API errors, or when it rate-limits.
The platform must trade correctly with this whole layer switched off.
"""
import json
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

import httpx

log = logging.getLogger("genai")


@dataclass
class GenAIResult:
    """
    Every AI response carries its provenance — FR-K-09, FR-K-11.
    `degraded` is True when the answer came from a fallback rather than a model.
    """
    text: str
    provider: str
    model: str
    degraded: bool = False
    latency_ms: int = 0
    guardrail: Optional[str] = None
    raw: Optional[dict] = None

    @property
    def provenance(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "degraded": self.degraded,
            "latency_ms": self.latency_ms,
            "guardrail": self.guardrail,
            "notice": (
                "Generated without a language model — deterministic fallback."
                if self.degraded else
                "AI-generated. Verify before acting on it."
            ),
        }


# ── Guardrails — FR-K-12 ────────────────────────────────────────────────────

INJECTION_MARKERS = [
    "ignore previous", "ignore all previous", "disregard the above",
    "system prompt", "you are now", "forget your instructions",
    "reveal your prompt", "print your instructions", "act as if",
    "bypass", "override your", "new instructions:",
]

ADVICE_MARKERS = [
    "should i buy", "should i sell", "what should i invest",
    "is it a good time to buy", "will the price go up", "will it go up",
    "recommend a stock", "what stock should", "guarantee",
    "predict the price", "is this a good investment",
]


def screen_input(text: str) -> Optional[str]:
    """Returns a guardrail code if the input must be refused, else None."""
    low = (text or "").lower()
    for marker in INJECTION_MARKERS:
        if marker in low:
            return "PROMPT_INJECTION"
    for marker in ADVICE_MARKERS:
        if marker in low:
            return "INVESTMENT_ADVICE"
    return None


REFUSALS = {
    "PROMPT_INJECTION": (
        "That request looks like an attempt to change how this assistant works, "
        "so it wasn't sent to the model. Ask about your orders, positions or "
        "trade history instead."
    ),
    "INVESTMENT_ADVICE": (
        "This assistant reports on your own account and explains platform "
        "terminology. It does not give investment advice or price predictions. "
        "Ask what you hold, how a position has performed, or what a term means."
    ),
}


# ── Providers ───────────────────────────────────────────────────────────────

class BaseProvider:
    name = "none"
    model = "fallback"

    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        raise NotImplementedError


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_tokens,
            },
        }
        with httpx.Client(timeout=25) as client:
            r = client.post(
                self.url,
                params={"key": self.api_key},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        r.raise_for_status()
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected Gemini response shape: {str(data)[:200]}")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        with httpx.Client(timeout=25) as client:
            r = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
        r.raise_for_status()
        data = r.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(parts).strip()


# ── Client ──────────────────────────────────────────────────────────────────

class GenAIClient:
    """
    The only place in the platform that talks to a language model.

    Stopping this service, removing the API key, or hitting a rate limit
    must never prevent order capture, execution or settlement — FR-K-10.
    """

    def __init__(self, provider_name: str, gemini_key: str = "", anthropic_key: str = ""):
        self.provider: BaseProvider
        p = (provider_name or "none").lower()

        if p == "gemini" and gemini_key:
            self.provider = GeminiProvider(gemini_key)
        elif p == "anthropic" and anthropic_key:
            self.provider = AnthropicProvider(anthropic_key)
        else:
            self.provider = BaseProvider()

        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.provider.available()

    def status(self) -> dict:
        return {
            "provider": self.provider.name,
            "model": self.provider.model,
            "enabled": self.enabled,
            "last_error": self.last_error,
            "note": (
                "Language model connected."
                if self.enabled else
                "No model configured — all AI features run on deterministic "
                "fallbacks. Core trading is unaffected."
            ),
        }

    def generate(
        self, system: str, user: str,
        fallback: str, max_tokens: int = 700,
    ) -> GenAIResult:
        """
        Attempt a model call. On refusal, absence or failure, return the
        fallback text marked as degraded. This method never raises.
        """
        guardrail = screen_input(user)
        if guardrail:
            return GenAIResult(
                text=REFUSALS[guardrail],
                provider=self.provider.name,
                model=self.provider.model,
                degraded=True,
                guardrail=guardrail,
            )

        if not self.enabled:
            return GenAIResult(
                text=fallback, provider="none", model="fallback", degraded=True,
            )

        started = time.time()
        try:
            text = self.provider.complete(system, user, max_tokens)
            self.last_error = None
            return GenAIResult(
                text=text.strip(),
                provider=self.provider.name,
                model=self.provider.model,
                degraded=False,
                latency_ms=int((time.time() - started) * 1000),
            )
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            self.last_error = f"HTTP {code}"
            log.warning("GenAI provider returned %s — using fallback", code)
        except Exception as e:  # noqa: BLE001 — degradation must be total
            self.last_error = str(e)[:200]
            log.warning("GenAI call failed (%s) — using fallback", self.last_error)

        return GenAIResult(
            text=fallback,
            provider=self.provider.name,
            model=self.provider.model,
            degraded=True,
            latency_ms=int((time.time() - started) * 1000),
        )

    def generate_json(
        self, system: str, user: str,
        fallback: dict, max_tokens: int = 500,
    ) -> tuple[dict, GenAIResult]:
        """Ask for structured JSON. Falls back to the supplied dict on any failure."""
        result = self.generate(
            system + "\n\nRespond with JSON only. No prose, no markdown fences.",
            user, fallback=json.dumps(fallback), max_tokens=max_tokens,
        )
        if result.degraded:
            return fallback, result

        cleaned = result.text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned.strip()), result
        except json.JSONDecodeError:
            result.degraded = True
            result.text = json.dumps(fallback)
            return fallback, result


def build_client() -> GenAIClient:
    from app.config import get_settings
    s = get_settings()
    return GenAIClient(
        provider_name=getattr(s, "genai_provider", "none"),
        gemini_key=getattr(s, "gemini_api_key", ""),
        anthropic_key=getattr(s, "anthropic_api_key", ""),
    )
