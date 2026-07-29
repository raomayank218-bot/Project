import { useEffect, useState } from 'react';
import { api } from '../services/api';
import LifecycleRail from './LifecycleRail';

const money = (v, dp = 2) =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });

function Provenance({ p }) {
  if (!p) return null;
  return (
    <div className="split tiny" style={{ marginTop: 8, flexWrap: 'wrap' }}>
      <span className={`chip ${p.degraded ? 'chip-warn' : 'chip-live'}`}>
        {p.degraded ? 'FALLBACK · NO MODEL' : `${p.provider} · ${p.model}`}
      </span>
      <span className="muted">{p.notice}</span>
      {p.latency_ms > 0 && <span className="muted mono">{p.latency_ms}ms</span>}
    </div>
  );
}

export default function Assistant({ account, isPaper, onTraded }) {
  const [status, setStatus] = useState(null);

  const [orderText, setOrderText] = useState('');
  const [parsed, setParsed] = useState(null);
  const [orderResult, setOrderResult] = useState(null);

  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState(null);

  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(null);

  useEffect(() => { api.aiStatus().then(setStatus).catch(() => {}); }, []);

  async function readOrder() {
    if (!orderText.trim()) return;
    setBusy('parse'); setParsed(null); setOrderResult(null);
    try {
      setParsed(await api.aiParseOrder(orderText));
    } catch (e) {
      setParsed({ parsed: { understood: false, clarification: e.message } });
    }
    setBusy(null);
  }

  // FR-K-02 — the only route to execution is the normal order path,
  // and only after the user has seen and confirmed the parsed order.
  async function sendOrder() {
    const p = parsed?.parsed;
    if (!p?.understood) return;
    setBusy('send');
    try {
      const payload = {
        account_id: account.id,
        instrument_id: p.instrument_id,
        side: p.side,
        quantity: Number(p.quantity),
        order_type: p.order_type || 'MARKET',
        time_in_force: p.time_in_force || 'DAY',
        is_paper: isPaper,
      };
      if (p.order_type === 'LIMIT' && p.price) payload.price = Number(p.price);
      setOrderResult(await api.placeOrder(payload));
      setParsed(null); setOrderText('');
      onTraded && onTraded();
    } catch (e) {
      setOrderResult({ success: false, message: e.message, reason_code: 'REQUEST_FAILED' });
    }
    setBusy(null);
  }

  async function askQuestion(q) {
    const text = q || question;
    if (!text.trim()) return;
    setBusy('ask'); setAnswer(null);
    try {
      setAnswer(await api.aiAsk(account.id, text, isPaper));
    } catch (e) {
      setAnswer({ question: text, answer: e.message, provenance: null });
    }
    setBusy(null);
  }

  async function getCommentary() {
    setBusy('note'); setNote(null);
    try {
      setNote(await api.aiCommentary(account.id, isPaper));
    } catch (e) {
      setNote({ commentary: e.message, provenance: null });
    }
    setBusy(null);
  }

  const suggestions = [
    'What do I hold?',
    'What are my biggest losers?',
    'How much buying power do I have?',
    'Why was my last order rejected?',
  ];

  return (
    <>
      {status && !status.enabled && (
        <div className="result bad">
          <span className="code">NO MODEL CONNECTED</span>
          {status.note} Set <code>GENAI_PROVIDER</code> and an API key in{' '}
          <code>.env</code> to enable full language understanding.
        </div>
      )}

      {/* Natural-language order entry */}
      <div className="panel">
        <div className="panel-head">
          <h2>Order in plain English</h2>
          <span className="spacer" />
          <span className="chip chip-mute">read, then confirmed</span>
        </div>
        <div className="panel-body">
          <div className="cmd">
            <span className="prompt">?</span>
            <input
              value={orderText}
              placeholder="buy me a hundred Apple shares at market"
              onChange={(e) => setOrderText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && readOrder()}
            />
            <button onClick={readOrder} disabled={busy === 'parse' || !orderText.trim()}>
              {busy === 'parse' ? '…' : 'READ'}
            </button>
          </div>
          <div className="cmd-hint">
            Nothing is sent until you confirm the order below.
          </div>

          {parsed && (
            parsed.parsed?.understood ? (
              <div className="result good" style={{ marginTop: 12 }}>
                <span className="code">CONFIRM BEFORE SENDING</span>
                <div className="mono" style={{ fontSize: 14, margin: '8px 0 12px' }}>
                  {parsed.parsed.side} {Number(parsed.parsed.quantity).toLocaleString()}{' '}
                  {parsed.parsed.instrument_id}{' '}
                  {parsed.parsed.order_type === 'LIMIT'
                    ? `@ ${parsed.parsed.price}` : '@ market'}{' '}
                  · {parsed.parsed.time_in_force}
                </div>
                <button className="btn btn-primary btn-sm" onClick={sendOrder}
                  disabled={busy === 'send'}>
                  {busy === 'send' ? 'Sending…' : 'Send this order'}
                </button>{' '}
                <button className="btn btn-sm" onClick={() => setParsed(null)}>Discard</button>
                <Provenance p={parsed.provenance} />
              </div>
            ) : (
              <div className="result bad" style={{ marginTop: 12 }}>
                <span className="code">NEEDS CLARIFICATION</span>
                {parsed.parsed?.clarification || 'That could not be read as an order.'}
                <Provenance p={parsed.provenance} />
              </div>
            )
          )}

          {orderResult && (
            <div style={{ marginTop: 14 }}>
              <div className={`result ${orderResult.success ? 'good' : 'bad'}`}>
                {orderResult.reason_code && <span className="code">{orderResult.reason_code}</span>}
                {orderResult.message}
              </div>
              <LifecycleRail lifecycle={orderResult.lifecycle} />
            </div>
          )}
        </div>
      </div>

      <div className="grid g-2-1">
        {/* Questions */}
        <div className="panel">
          <div className="panel-head"><h2>Ask about this account</h2></div>
          <div className="panel-body">
            <div className="cmd">
              <span className="prompt">?</span>
              <input
                value={question}
                placeholder="what were my biggest losers?"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && askQuestion()}
              />
              <button onClick={() => askQuestion()} disabled={busy === 'ask'}>
                {busy === 'ask' ? '…' : 'ASK'}
              </button>
            </div>

            <div className="split" style={{ marginTop: 10, flexWrap: 'wrap', gap: 6 }}>
              {suggestions.map((s) => (
                <button key={s} className="btn btn-sm"
                  onClick={() => { setQuestion(s); askQuestion(s); }}>
                  {s}
                </button>
              ))}
            </div>

            {answer && (
              <div className="result good" style={{ marginTop: 14 }}>
                <span className="code">{answer.question}</span>
                <div style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{answer.answer}</div>
                <Provenance p={answer.provenance} />
              </div>
            )}
          </div>
        </div>

        {/* Commentary */}
        <div className="panel">
          <div className="panel-head">
            <h2>Performance note</h2>
            <span className="spacer" />
            <button className="btn btn-sm" onClick={getCommentary} disabled={busy === 'note'}>
              {busy === 'note' ? 'Writing…' : 'Write'}
            </button>
          </div>
          <div className="panel-body">
            {!note ? (
              <div className="tiny muted">
                Generates a short factual note on what drove performance,
                using only figures the platform has already computed.
              </div>
            ) : (
              <>
                <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                  {note.commentary}
                </div>
                <Provenance p={note.provenance} />
              </>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-body tiny muted">
          Every interaction here — prompt, response, model and provenance — is
          written to the audit log. The assistant never submits an order on its
          own, gives no investment advice, and the platform trades normally with
          it switched off.
        </div>
      </div>
    </>
  );
}
