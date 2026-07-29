import { useEffect, useState } from 'react';
import { api } from '../services/api';

const money = (v, dp = 2) => {
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  });
};
const qty = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
const dirClass = (v) => (Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'flat');
const signed = (v) => (Number(v) > 0 ? '+' : '') + money(v);

export default function Dashboard({ account, isPaper }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!account) return;
    let live = true;
    const load = () =>
      api.summary(account.id, isPaper)
        .then((d) => { if (live) { setData(d); setError(null); } })
        .catch((e) => { if (live) setError(e.message); });
    load();
    const t = setInterval(load, 8000);
    return () => { live = false; clearInterval(t); };
  }, [account, isPaper]);

  if (error) return <div className="panel"><div className="empty"><strong>Could not load the portfolio</strong>{error}</div></div>;
  if (!data) return <div className="panel"><div className="empty">Loading positions…</div></div>;

  const pnl = data.pnl;
  const totalPnl = Number(pnl.total);

  return (
    <>
      <div className="grid g4">
        <div className="panel"><div className="panel-body fig">
          <div className="k">Portfolio value</div>
          <div className="v">{money(data.valuation.total_value)}</div>
          <div className="d muted">{data.position_count} position{data.position_count === 1 ? '' : 's'}</div>
        </div></div>

        <div className="panel"><div className="panel-body fig">
          <div className="k">Total P&amp;L</div>
          <div className={`v ${dirClass(totalPnl)}`}>{signed(totalPnl)}</div>
          <div className={`d ${dirClass(pnl.unrealised_pct)}`}>
            {signed(pnl.unrealised_pct)}% unrealised
          </div>
        </div></div>

        <div className="panel"><div className="panel-body fig">
          <div className="k">Buying power</div>
          <div className="v">{money(data.cash.buying_power)}</div>
          <div className="d muted">{money(data.cash.unsettled)} unsettled</div>
        </div></div>

        <div className="panel"><div className="panel-body fig">
          <div className="k">Positions at cost</div>
          <div className="v">{money(data.valuation.total_cost_basis)}</div>
          <div className="d muted">{money(data.valuation.positions_value)} at market</div>
        </div></div>
      </div>

      <div className="grid g-2-1">
        <div className="panel">
          <div className="panel-head">
            <h2>Positions</h2>
            <span className="spacer" />
            <span className="chip chip-mute">FIFO cost basis</span>
          </div>
          <div className="panel-body flush">
            {data.positions.length === 0 ? (
              <div className="empty">
                <strong>No positions yet</strong>
                Place an order from the Trade screen to open one.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th className="num">Qty</th>
                    <th className="num">Avg cost</th>
                    <th className="num">Last</th>
                    <th className="num">Value</th>
                    <th className="num">Unrealised</th>
                    <th className="num">%</th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.map((p) => (
                    <tr key={p.instrument_id}>
                      <td className="ticker">{p.instrument_id}</td>
                      <td className="num">{qty(p.quantity)}</td>
                      <td className="num">{money(p.avg_cost)}</td>
                      <td className="num">{p.last_price ? money(p.last_price) : '—'}</td>
                      <td className="num">{money(p.market_value)}</td>
                      <td className={`num ${dirClass(p.unrealised_pnl)}`}>
                        {signed(p.unrealised_pnl)}
                      </td>
                      <td className={`num ${dirClass(p.unrealised_pnl_pct)}`}>
                        {signed(p.unrealised_pnl_pct)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Allocation</h2></div>
          <div className="panel-body">
            {data.allocation.length === 0 ? (
              <div className="tiny muted">Nothing allocated yet.</div>
            ) : (
              data.allocation.map((a) => (
                <div key={a.instrument_id} className="bar-row">
                  <span className="ticker tiny" style={{ width: 46 }}>{a.instrument_id}</span>
                  <span className="bar-track">
                    <span
                      className="bar-fill"
                      style={{
                        width: `${Math.min(100, Number(a.pct_of_portfolio))}%`,
                        background: a.instrument_id === 'CASH' ? 'var(--ink-3)' : 'var(--signal)',
                      }}
                    />
                  </span>
                  <span className="num tiny mono" style={{ width: 46 }}>
                    {money(a.pct_of_portfolio, 1)}%
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}
