import { useEffect, useState } from 'react';
import { api } from '../services/api';
import LifecycleRail from './LifecycleRail';

const money = (v, dp = 2) =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
const qty = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

export default function TradeTicket({ account, isPaper, onDone }) {
  const [instruments, setInstruments] = useState([]);
  const [symbol, setSymbol] = useState('AAPL');
  const [side, setSide] = useState('BUY');
  const [quantity, setQuantity] = useState('100');
  const [orderType, setOrderType] = useState('MARKET');
  const [price, setPrice] = useState('');
  const [tif, setTif] = useState('DAY');

  const [book, setBook] = useState(null);
  const [command, setCommand] = useState('');
  const [parsed, setParsed] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.instruments().then((d) => setInstruments(d.instruments)).catch(() => {}); }, []);

  useEffect(() => {
    if (!symbol) return;
    let live = true;
    const load = () => api.book(symbol).then((b) => live && setBook(b)).catch(() => live && setBook(null));
    load();
    const t = setInterval(load, 6000);
    return () => { live = false; clearInterval(t); };
  }, [symbol]);

  async function submitForm(e) {
    e.preventDefault();
    setBusy(true); setResult(null); setParsed(null);
    const payload = {
      account_id: account.id,
      instrument_id: symbol,
      side, quantity: Number(quantity),
      order_type: orderType,
      time_in_force: tif,
      is_paper: isPaper,
    };
    if (orderType === 'LIMIT') payload.price = Number(price);
    try {
      setResult(await api.placeOrder(payload));
      onDone && onDone();
    } catch (err) {
      setResult({ success: false, message: err.message, reason_code: 'REQUEST_FAILED' });
    }
    setBusy(false);
  }

  // FR-A-13 / FR-K-02 — parse first, then confirm. Never straight to execution.
  async function parseCommand() {
    if (!command.trim()) return;
    setBusy(true); setResult(null); setParsed(null);
    try {
      const r = await api.placeCommand({
        account_id: account.id, command, is_paper: isPaper, confirm: false,
      });
      setParsed(r.parsed);
    } catch (err) {
      setResult({ success: false, message: err.message, reason_code: 'PARSE_FAILED' });
    }
    setBusy(false);
  }

  async function confirmCommand() {
    setBusy(true);
    try {
      const r = await api.placeCommand({
        account_id: account.id, command, is_paper: isPaper, confirm: true,
      });
      setResult(r); setParsed(null); setCommand('');
      onDone && onDone();
    } catch (err) {
      setResult({ success: false, message: err.message, reason_code: 'REQUEST_FAILED' });
    }
    setBusy(false);
  }

  const last = instruments.find((i) => i.id === symbol)?.last_price;

  return (
    <>
      {/* Command entry — the syntax clients already know */}
      <div className="panel">
        <div className="panel-head">
          <h2>Command</h2>
          <span className="spacer" />
          <span className="chip chip-mute">parsed, then confirmed</span>
        </div>
        <div className="panel-body">
          <div className="cmd">
            <span className="prompt">&gt;</span>
            <input
              className="mono"
              value={command}
              placeholder="BUY 100 AAPL @MKT DAY"
              onChange={(e) => setCommand(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && parseCommand()}
              spellCheck={false}
            />
            <button onClick={parseCommand} disabled={busy || !command.trim()}>PARSE</button>
          </div>
          <div className="cmd-hint">
            BUY|SELL &lt;qty&gt; &lt;TICKER&gt; [@MKT | @price] [DAY|GTC|IOC|FOK]
          </div>

          {parsed && (
            <div className="result good" style={{ marginTop: 12 }}>
              <span className="code">Confirm this order before it is sent</span>
              <div className="mono" style={{ fontSize: 13, margin: '6px 0 10px' }}>
                {parsed.side} {qty(parsed.quantity)} {parsed.instrument_id} @{parsed.price}
                {' · '}{parsed.order_type} · {parsed.time_in_force}
              </div>
              <button className="btn btn-primary btn-sm" onClick={confirmCommand} disabled={busy}>
                Send order
              </button>{' '}
              <button className="btn btn-sm" onClick={() => setParsed(null)}>Discard</button>
            </div>
          )}
        </div>
      </div>

      <div className="grid g-2-1">
        {/* Ticket */}
        <div className="panel">
          <div className="panel-head"><h2>Order ticket</h2></div>
          <div className="panel-body">
            <form onSubmit={submitForm}>
              <div className="grid g2">
                <label className="f">
                  <span className="lab">Instrument</span>
                  <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                    {instruments.map((i) => (
                      <option key={i.id} value={i.id}>{i.id} — {i.name}</option>
                    ))}
                  </select>
                </label>
                <label className="f">
                  <span className="lab">Side</span>
                  <div className="seg">
                    <button type="button"
                      className={side === 'BUY' ? 'on-buy' : ''}
                      onClick={() => setSide('BUY')}>BUY</button>
                    <button type="button"
                      className={side === 'SELL' ? 'on-sell' : ''}
                      onClick={() => setSide('SELL')}>SELL</button>
                  </div>
                </label>
              </div>

              <div className="grid g2">
                <label className="f">
                  <span className="lab">Quantity</span>
                  <input className="mono" type="number" min="1" value={quantity}
                    onChange={(e) => setQuantity(e.target.value)} required />
                </label>
                <label className="f">
                  <span className="lab">Type</span>
                  <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                    <option value="MARKET">Market</option>
                    <option value="LIMIT">Limit</option>
                  </select>
                </label>
              </div>

              <div className="grid g2">
                <label className="f">
                  <span className="lab">Limit price</span>
                  <input className="mono" type="number" step="0.01" value={price}
                    placeholder={orderType === 'MARKET' ? 'at market' : String(last || '')}
                    disabled={orderType === 'MARKET'}
                    onChange={(e) => setPrice(e.target.value)}
                    required={orderType === 'LIMIT'} />
                </label>
                <label className="f">
                  <span className="lab">Time in force</span>
                  <select value={tif} onChange={(e) => setTif(e.target.value)}>
                    <option value="DAY">Day</option>
                    <option value="GTC">Good till cancelled</option>
                    <option value="IOC">Immediate or cancel</option>
                    <option value="FOK">Fill or kill</option>
                  </select>
                </label>
              </div>

              <div className="split" style={{ marginTop: 4 }}>
                <button className={`btn btn-block ${side === 'BUY' ? 'btn-primary' : 'btn-danger'}`}
                  disabled={busy}>
                  {busy ? 'Working…' : `${side} ${qty(quantity || 0)} ${symbol}`}
                </button>
              </div>
              {last && (
                <div className="tiny muted mono" style={{ marginTop: 8 }}>
                  Last {money(last)} · indicative {money(Number(last) * Number(quantity || 0))}
                </div>
              )}
            </form>
          </div>
        </div>

        {/* Book */}
        <div className="panel">
          <div className="panel-head">
            <h2>Depth · {symbol}</h2>
            <span className="spacer" />
            {book && book.spread && (
              <span className="chip chip-mute">spread {money(book.spread)}</span>
            )}
          </div>
          <div className="panel-body flush">
            {!book ? (
              <div className="empty">No depth available.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th className="num">Bid qty</th><th className="num">Bid</th>
                    <th className="num">Ask</th><th className="num">Ask qty</th>
                  </tr>
                </thead>
                <tbody>
                  {book.bids.map((b, i) => (
                    <tr key={i}>
                      <td className="num mono">{qty(b.quantity)}</td>
                      <td className="num mono up">{money(b.price)}</td>
                      <td className="num mono down">{book.asks[i] ? money(book.asks[i].price) : ''}</td>
                      <td className="num mono">{book.asks[i] ? qty(book.asks[i].quantity) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="tiny muted" style={{ padding: '8px 14px' }}>
              Depth is modelled from OHLCV — the dataset carries no book.
            </div>
          </div>
        </div>
      </div>

      {/* Result + the lifecycle rail */}
      {result && (
        <div className="panel">
          <div className="panel-head">
            <h2>Order result</h2>
            <span className="spacer" />
            {result.correlation_id && (
              <span className="chip chip-mute">{result.correlation_id.slice(0, 8)}</span>
            )}
          </div>
          <div className="panel-body">
            <div className={`result ${result.success ? 'good' : 'bad'}`}>
              {result.reason_code && <span className="code">{result.reason_code}</span>}
              {result.message}
            </div>

            {result.trade && (
              <div className="grid g4" style={{ marginBottom: 14 }}>
                <div className="fig"><div className="k">Filled</div>
                  <div className="v sm">{qty(result.trade.quantity)}</div></div>
                <div className="fig"><div className="k">Avg price</div>
                  <div className="v sm">{money(result.trade.price)}</div></div>
                <div className="fig"><div className="k">Charges</div>
                  <div className="v sm">
                    {money(Number(result.trade.commission) + Number(result.trade.exchange_fee) + Number(result.trade.tax))}
                  </div></div>
                <div className="fig"><div className="k">Settles</div>
                  <div className="v sm">{result.trade.settlement_date}</div></div>
              </div>
            )}

            <LifecycleRail lifecycle={result.lifecycle} />
          </div>
        </div>
      )}
    </>
  );
}
