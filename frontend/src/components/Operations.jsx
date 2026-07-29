import { useEffect, useState } from 'react';
import { api } from '../services/api';

const money = (v, dp = 2) =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
const clean = (v) => String(v ?? '').replace(/^\w+\./, '');

export default function Operations({ role }) {
  const [dash, setDash] = useState(null);
  const [settle, setSettle] = useState(null);
  const [kill, setKill] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.opsDashboard().then(setDash).catch(() => {});
    api.settlements().then(setSettle).catch(() => {});
    api.killSwitch().then(setKill).catch(() => {});
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  async function toggleKill() {
    setBusy(true);
    try {
      kill?.active ? await api.killDeactivate() : await api.killActivate();
      load();
    } catch (e) {
      alert(e.message);
    }
    setBusy(false);
  }

  const canKill = ['RISK', 'ADMIN', 'TRADER'].includes(clean(role));
  const stp = dash?.stp;

  return (
    <>
      <div className="grid g4">
        <div className="panel"><div className="panel-body fig">
          <div className="k">STP rate</div>
          <div className="v">{stp?.stp_rate != null ? `${stp.stp_rate}%` : '—'}</div>
          <div className="d muted">{stp?.straight_through ?? 0} of {stp?.total_trades ?? 0} clean</div>
        </div></div>

        <div className="panel"><div className="panel-body fig">
          <div className="k">Open breaks</div>
          <div className={`v ${dash?.exceptions?.open_count > 0 ? 'down' : ''}`}>
            {dash?.exceptions?.open_count ?? 0}
          </div>
          <div className="d muted">{dash?.exceptions?.sla_breached ?? 0} past SLA</div>
        </div></div>

        <div className="panel"><div className="panel-body fig">
          <div className="k">Settlements pending</div>
          <div className="v">{settle?.pending_count ?? 0}</div>
          <div className={`d ${settle?.failed_count > 0 ? 'down' : 'muted'}`}>
            {settle?.failed_count ?? 0} failed
          </div>
        </div></div>

        <div className="panel">
          <div className="panel-body fig">
            <div className="k">Order submission</div>
            <div className={`v sm ${kill?.active ? 'down' : 'up'}`}>
              {kill?.active ? 'HALTED' : 'OPEN'}
            </div>
            {canKill && (
              <button
                className={`btn btn-sm ${kill?.active ? '' : 'btn-danger'}`}
                style={{ marginTop: 8 }}
                onClick={toggleKill}
                disabled={busy}
              >
                {kill?.active ? 'Resume trading' : 'Halt all trading'}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="grid g2">
        <div className="panel">
          <div className="panel-head"><h2>Orders by state</h2></div>
          <div className="panel-body flush">
            {!dash?.orders_by_state || Object.keys(dash.orders_by_state).length === 0 ? (
              <div className="empty">No orders yet.</div>
            ) : (
              <table>
                <thead><tr><th>State</th><th className="num">Count</th></tr></thead>
                <tbody>
                  {Object.entries(dash.orders_by_state)
                    .sort((a, b) => b[1] - a[1])
                    .map(([state, count]) => (
                      <tr key={state}>
                        <td className="mono tiny">{clean(state)}</td>
                        <td className="num">{count}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Settlement pipeline</h2></div>
          <div className="panel-body flush">
            {!settle || settle.pending.length + settle.failed.length === 0 ? (
              <div className="empty">
                <strong>Nothing outstanding</strong>
                Settled trades leave the pipeline.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Instrument</th><th>Side</th><th className="num">Qty</th>
                    <th className="num">Net</th><th>Settles</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[...settle.failed, ...settle.pending].map((s) => (
                    <tr key={s.id}>
                      <td className="ticker">{s.instrument_id}</td>
                      <td className={s.side === 'BUY' ? 'up mono' : 'down mono'}>{s.side}</td>
                      <td className="num">{Number(s.quantity).toLocaleString()}</td>
                      <td className="num">{money(s.net_consideration)}</td>
                      <td className="mono tiny">{s.settlement_date}</td>
                      <td>
                        <span className={`chip ${clean(s.status) === 'FAILED' ? 'chip-bad' : 'chip-live'}`}>
                          {clean(s.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
