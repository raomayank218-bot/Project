import { useEffect, useState, useCallback } from 'react';
import { api, auth } from './services/api';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import TradeTicket from './components/TradeTicket';
import Blotter from './components/Blotter';
import Exceptions from './components/Exceptions';
import Operations from './components/Operations';
import Market from './components/Market';

const clean = (v) => String(v ?? '').replace(/^\w+\./, '');

const VIEWS = [
  { id: 'dashboard', label: 'Portfolio' },
  { id: 'trade', label: 'Trade' },
  { id: 'market', label: 'Market' },
  { id: 'blotter', label: 'Blotter' },
  { id: 'exceptions', label: 'Breaks' },
  { id: 'ops', label: 'Operations' },
];

export default function App() {
  const [signedIn, setSignedIn] = useState(!!auth.token);
  const [view, setView] = useState('dashboard');
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState(null);
  const [breakCount, setBreakCount] = useState(0);
  const [refresh, setRefresh] = useState(0);

  const user = auth.user;

  const loadAccounts = useCallback(() => {
    api.accounts()
      .then((d) => {
        setAccounts(d.accounts);
        setAccountId((prev) => prev || d.accounts.find((a) => !a.is_paper)?.id || d.accounts[0]?.id);
      })
      .catch(() => {});
  }, []);

  useEffect(() => { if (signedIn) loadAccounts(); }, [signedIn, loadAccounts, refresh]);

  useEffect(() => {
    if (!signedIn) return;
    const load = () =>
      api.exceptionStats().then((s) => setBreakCount(s.open_count)).catch(() => {});
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [signedIn, refresh]);

  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;

  const account = accounts.find((a) => a.id === accountId);
  const isPaper = !!account?.is_paper;

  async function signOut() {
    await api.logout();
    auth.clear();
    setSignedIn(false);
  }

  const title = VIEWS.find((v) => v.id === view)?.label || '';

  return (
    <div className={`shell ${isPaper ? 'papermode' : ''}`}>
      <nav className="rail">
        <div className="rail-brand">
          <div className="mark">STP&nbsp;/&nbsp;Trading</div>
          <div className="sub">Nomura · 2026</div>
        </div>

        <div className="rail-nav">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              className={`rail-item ${view === v.id ? 'on' : ''}`}
              onClick={() => setView(v.id)}
            >
              <span className="label">{v.label}</span>
              {v.id === 'exceptions' && breakCount > 0 && (
                <span className="rail-badge">{breakCount}</span>
              )}
            </button>
          ))}
        </div>

        <div className="rail-foot">
          <div className="who">{user?.username}</div>
          <div className="role">{clean(user?.role)}</div>
          <button onClick={signOut}>Sign out</button>
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <h1>{title}</h1>
          {isPaper && <span className="paper-flag">PAPER — NOT LIVE</span>}
          <span className="spacer" />

          {accounts.length > 0 && (
            <select
              value={accountId || ''}
              onChange={(e) => setAccountId(e.target.value)}
              style={{ width: 220 }}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.account_name}{a.is_paper ? ' · paper' : ''}
                </option>
              ))}
            </select>
          )}
        </header>

        <main className="content">
          {!account && accounts.length === 0 ? (
            <div className="panel">
              <div className="empty">
                <strong>No accounts available</strong>
                Your user has no entitled accounts.
              </div>
            </div>
          ) : (
            <>
              {view === 'dashboard' && <Dashboard account={account} isPaper={isPaper} />}
              {view === 'trade' && (
                <TradeTicket
                  account={account}
                  isPaper={isPaper}
                  onDone={() => setRefresh((n) => n + 1)}
                />
              )}
              {view === 'market' && <Market />}
              {view === 'blotter' && <Blotter isPaper={isPaper} />}
              {view === 'exceptions' && <Exceptions onCount={setBreakCount} />}
              {view === 'ops' && <Operations role={user?.role} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
