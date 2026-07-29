import { useState } from 'react';
import { api } from '../services/api';

export default function Login({ onSignedIn }) {
  const [username, setUsername] = useState('trader1');
  const [password, setPassword] = useState('Password123!');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(username, password);
      onSignedIn();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="mark">STP&nbsp;/&nbsp;Trading</div>
        <div className="sub">Straight-through processing</div>

        {error && <div className="login-err">{error}</div>}

        <label className="f">
          <span className="lab">User</span>
          <input
            className="mono"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </label>

        <label className="f">
          <span className="lab">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="hintbox">
          Seeded users, all with password <code>Password123!</code><br />
          <code>trader1</code> execution desk · <code>ops1</code> operations<br />
          <code>risk1</code> risk · <code>tom</code> client · <code>admin</code> everything
        </div>
      </form>
    </div>
  );
}
