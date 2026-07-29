import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
  BarChart, Bar, ReferenceLine,
} from 'recharts';
import { api } from '../services/api';

const money = (v, dp = 2) =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });

export default function Market() {
  const [instruments, setInstruments] = useState([]);
  const [symbol, setSymbol] = useState('AAPL');
  const [interval, setInterval_] = useState('1min');
  const [bars, setBars] = useState([]);
  const [sent, setSent] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.instruments().then((d) => setInstruments(d.instruments)).catch(() => {}); }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.prices(symbol, interval, interval === 'daily' ? 200 : 390).catch(() => ({ bars: [] })),
      api.sentiment(symbol).catch(() => null),
    ]).then(([p, s]) => {
      setBars(p.bars.map((b) => ({
        t: new Date(b.timestamp),
        close: Number(b.close),
        volume: Number(b.volume),
      })));
      setSent(s);
      setLoading(false);
    });
  }, [symbol, interval]);

  const first = bars[0]?.close;
  const last = bars[bars.length - 1]?.close;
  const change = first && last ? ((last - first) / first) * 100 : 0;

  const sentData = (sent?.scores || []).map((s) => ({
    date: s.date.slice(5),
    score: Number(s.avg_score),
    count: s.article_count,
  }));

  const fmtX = (d) =>
    interval === 'daily'
      ? d.toLocaleDateString([], { month: 'short', day: 'numeric' })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h2>Price</h2>
          <span className="spacer" />
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}
            style={{ width: 200 }}>
            {instruments.map((i) => <option key={i.id} value={i.id}>{i.id} — {i.name}</option>)}
          </select>
          <div className="seg" style={{ width: 160 }}>
            <button className={interval === '1min' ? 'on-buy' : ''}
              onClick={() => setInterval_('1min')}>1 MIN</button>
            <button className={interval === 'daily' ? 'on-buy' : ''}
              onClick={() => setInterval_('daily')}>DAILY</button>
          </div>
        </div>
        <div className="panel-body">
          {loading ? (
            <div className="empty">Loading price history…</div>
          ) : bars.length === 0 ? (
            <div className="empty"><strong>No price data</strong>This instrument has no bars at this interval.</div>
          ) : (
            <>
              <div className="split" style={{ marginBottom: 12 }}>
                <span className="fig">
                  <span className="v" style={{ fontSize: 24 }}>{money(last)}</span>
                </span>
                <span className={`mono ${change >= 0 ? 'up' : 'down'}`}>
                  {change >= 0 ? '+' : ''}{change.toFixed(2)}% over {bars.length} bars
                </span>
              </div>
              <div style={{ height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={bars} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                    <CartesianGrid stroke="var(--rule-soft)" vertical={false} />
                    <XAxis dataKey="t" tickFormatter={fmtX} minTickGap={60}
                      tick={{ fontSize: 10, fill: 'var(--ink-3)', fontFamily: 'var(--mono)' }}
                      stroke="var(--rule)" />
                    <YAxis domain={['auto', 'auto']} width={62}
                      tick={{ fontSize: 10, fill: 'var(--ink-3)', fontFamily: 'var(--mono)' }}
                      stroke="var(--rule)" tickFormatter={(v) => money(v, 0)} />
                    <Tooltip
                      labelFormatter={(d) => new Date(d).toLocaleString()}
                      formatter={(v) => [money(v), 'Close']}
                      contentStyle={{
                        fontFamily: 'var(--mono)', fontSize: 11,
                        border: '1px solid var(--rule)', borderRadius: 3,
                      }} />
                    <Line type="monotone" dataKey="close" stroke="var(--signal)"
                      strokeWidth={1.6} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>News sentiment · {symbol}</h2>
          <span className="spacer" />
          {sent && (
            <span className="chip chip-mute">
              {sent.total_article_mentions} mentions · {sent.day_count} days
            </span>
          )}
        </div>
        <div className="panel-body">
          {sent?.coverage_warning && (
            <div className="result bad" style={{ marginBottom: 12 }}>
              <span className="code">THIN COVERAGE</span>
              {sent.coverage_warning}
            </div>
          )}
          {sentData.length === 0 ? (
            <div className="empty">No sentiment records for this instrument.</div>
          ) : (
            <div style={{ height: 170 }}>
              <ResponsiveContainer>
                <BarChart data={sentData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                  <CartesianGrid stroke="var(--rule-soft)" vertical={false} />
                  <XAxis dataKey="date" minTickGap={30}
                    tick={{ fontSize: 10, fill: 'var(--ink-3)', fontFamily: 'var(--mono)' }}
                    stroke="var(--rule)" />
                  <YAxis width={50} domain={[-0.5, 0.5]}
                    tick={{ fontSize: 10, fill: 'var(--ink-3)', fontFamily: 'var(--mono)' }}
                    stroke="var(--rule)" />
                  <ReferenceLine y={0} stroke="var(--ink-3)" />
                  <Tooltip
                    formatter={(v, n, p) => [v.toFixed(3), `${p.payload.count} articles`]}
                    contentStyle={{
                      fontFamily: 'var(--mono)', fontSize: 11,
                      border: '1px solid var(--rule)', borderRadius: 3,
                    }} />
                  <Bar dataKey="score" fill="var(--signal)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="tiny muted" style={{ marginTop: 10 }}>
            Sentiment is indicative only and is not investment advice. Scores are
            relevance-weighted daily averages from the news dataset.
          </div>
        </div>
      </div>
    </>
  );
}
