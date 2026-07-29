import { useEffect, useState } from 'react';
import { api } from '../services/api';

const money = (v, dp = 2) =>
  v == null ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
const qty = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

const STATE_CHIP = {
  SETTLED: 'chip-ok', FILLED: 'chip-ok', MATCHED: 'chip-ok',
  CLEARED: 'chip-live', SETTLEMENT_INSTRUCTED: 'chip-live', WORKING: 'chip-live',
  PARTIALLY_FILLED: 'chip-live', RISK_APPROVED: 'chip-live', VALIDATED: 'chip-live',
  RECEIVED: 'chip-mute',
  REJECTED: 'chip-bad', CANCELLED: 'chip-bad', EXPIRED: 'chip-bad',
  SETTLEMENT_FAILED: 'chip-bad',
  EXCEPTION: 'chip-warn', SUSPENDED: 'chip-warn',
};

export default function Blotter({ isPaper }) {
  const [orders, setOrders] = useState([]);
  const [audit, setAudit] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.orders(`?is_paper=${isPaper}&limit=200`)
        .then((d) => { if (live) { setOrders(d.orders); setError(null); } })
        .catch((e) => live && setError(e.message));
    load();
    const t = setInterval(load, 6000);
    return () => { live = false; clearInterval(t); };
  }, [isPaper]);

  async function showAudit(id) {
    if (openId === id) { setOpenId(null); setAudit(null); return; }
    setOpenId(id); setAudit(null);
    try { setAudit(await api.orderAudit(id)); } catch { setAudit({ audit_trail: [] }); }
  }

  if (error) return <div className="panel"><div className="empty"><strong>Could not load orders</strong>{error}</div></div>;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Order blotter</h2>
        <span className="spacer" />
        <span className="chip chip-mute">{orders.length} orders</span>
      </div>
      <div className="panel-body flush">
        {orders.length === 0 ? (
          <div className="empty">
            <strong>No orders yet</strong>
            Orders you place will appear here with their live state.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th><th>Instrument</th><th>Side</th><th>Type</th>
                <th className="num">Qty</th><th className="num">Filled</th>
                <th className="num">Avg price</th><th>State</th><th>Reason</th><th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <>
                  <tr key={o.id}>
                    <td className="mono tiny">
                      {o.received_at ? new Date(o.received_at).toLocaleTimeString() : '—'}
                    </td>
                    <td className="ticker">{o.instrument_id}</td>
                    <td className={o.side === 'BUY' ? 'up mono' : 'down mono'}>{o.side}</td>
                    <td className="mono tiny">{o.order_type}</td>
                    <td className="num">{qty(o.quantity)}</td>
                    <td className="num">{qty(o.filled_quantity)}</td>
                    <td className="num">{money(o.avg_fill_price)}</td>
                    <td>
                      <span className={`chip ${STATE_CHIP[o.state] || 'chip-mute'}`}>{o.state}</span>
                    </td>
                    <td className="tiny muted mono">{o.reject_reason || ''}</td>
                    <td>
                      <button className="btn btn-sm" onClick={() => showAudit(o.id)}>
                        {openId === o.id ? 'Hide' : 'Audit'}
                      </button>
                    </td>
                  </tr>
                  {openId === o.id && (
                    <tr key={`${o.id}-audit`}>
                      <td colSpan={10} style={{ background: 'var(--surface-2)', padding: 0 }}>
                        <div style={{ padding: '12px 14px' }}>
                          <div className="tiny muted" style={{ marginBottom: 8 }}>
                            Reconstructed from the append-only audit log.
                          </div>
                          {!audit ? (
                            <div className="tiny muted">Loading…</div>
                          ) : audit.audit_trail.length === 0 ? (
                            <div className="tiny muted">No audit entries.</div>
                          ) : (
                            <table>
                              <thead>
                                <tr>
                                  <th>When</th><th>Actor</th><th>Action</th>
                                  <th>From</th><th>To</th><th>Reason</th>
                                </tr>
                              </thead>
                              <tbody>
                                {audit.audit_trail.map((e, i) => (
                                  <tr key={i}>
                                    <td className="mono tiny">
                                      {new Date(e.occurred_at).toLocaleTimeString()}
                                    </td>
                                    <td className="mono tiny">{e.actor_id}</td>
                                    <td className="mono tiny">{e.action}</td>
                                    <td className="mono tiny">{e.before_state?.state || ''}</td>
                                    <td className="mono tiny">{e.after_state?.state || ''}</td>
                                    <td className="mono tiny muted">{e.reason_code || ''}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
