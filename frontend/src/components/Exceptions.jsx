import { useEffect, useState } from 'react';
import { api } from '../services/api';

const SEV_CHIP = {
  CRITICAL: 'chip-bad', HIGH: 'chip-bad', MEDIUM: 'chip-warn', LOW: 'chip-mute',
};
const clean = (v) => String(v ?? '').replace(/^\w+\./, '');

export default function Exceptions({ onCount }) {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [action, setAction] = useState('');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [triage, setTriage] = useState({});

  const load = () => {
    api.exceptions('?limit=200')
      .then((d) => { setRows(d.exceptions); onCount && onCount(d.exceptions.filter(e => clean(e.status) === 'OPEN').length); })
      .catch(() => {});
    api.exceptionStats().then(setStats).catch(() => {});
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  // FR-K-08 — advisory only; the analyst confirms and records the action
  async function getTriage(id) {
    setTriage((t) => ({ ...t, [id]: { loading: true } }));
    try {
      const r = await api.aiTriage(id);
      setTriage((t) => ({ ...t, [id]: r }));
    } catch (e) {
      setTriage((t) => ({ ...t, [id]: { suggestion: e.message } }));
    }
  }

  async function resolve(id) {
    if (!reason.trim()) {
      setNote({ ok: false, text: 'A reason is required before an exception can be closed.' });
      return;
    }
    setBusy(true);
    try {
      await api.resolveException(id, action || 'Reviewed', reason);
      setNote({ ok: true, text: 'Exception resolved and written to the audit log.' });
      setOpenId(null); setAction(''); setReason('');
      load();
    } catch (e) {
      setNote({ ok: false, text: e.message });
    }
    setBusy(false);
  }

  const open = rows.filter((r) => ['OPEN', 'IN_PROGRESS'].includes(clean(r.status)));

  return (
    <>
      {stats && (
        <div className="grid g4">
          <div className="panel"><div className="panel-body fig">
            <div className="k">Open</div><div className="v">{stats.open_count}</div>
          </div></div>
          <div className="panel"><div className="panel-body fig">
            <div className="k">SLA breached</div>
            <div className={`v ${stats.sla_breached > 0 ? 'down' : ''}`}>{stats.sla_breached}</div>
          </div></div>
          <div className="panel"><div className="panel-body fig">
            <div className="k">By severity</div>
            <div className="d mono">
              {Object.entries(stats.by_severity).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}
            </div>
          </div></div>
          <div className="panel"><div className="panel-body fig">
            <div className="k">By code</div>
            <div className="d mono">
              {Object.entries(stats.by_code).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}
            </div>
          </div></div>
        </div>
      )}

      {note && (
        <div className={`result ${note.ok ? 'good' : 'bad'}`}>{note.text}</div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Break queue</h2>
          <span className="spacer" />
          <span className="chip chip-mute">{open.length} needing action</span>
        </div>
        <div className="panel-body flush">
          {rows.length === 0 ? (
            <div className="empty">
              <strong>Nothing in the queue</strong>
              Failures anywhere in the lifecycle land here with an owner and an SLA.
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Raised</th><th>Code</th><th>Severity</th><th>Status</th>
                  <th>Entity</th><th>Description</th><th>SLA due</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const status = clean(e.status);
                  const breached = e.sla_due_at && new Date(e.sla_due_at) < new Date() && status !== 'RESOLVED';
                  return (
                    <>
                      <tr key={e.id}>
                        <td className="mono tiny">
                          {e.raised_at ? new Date(e.raised_at).toLocaleTimeString() : '—'}
                        </td>
                        <td><span className="chip chip-mute">{clean(e.code)}</span></td>
                        <td>
                          <span className={`chip ${SEV_CHIP[clean(e.severity)] || 'chip-mute'}`}>
                            {clean(e.severity)}
                          </span>
                        </td>
                        <td>
                          <span className={`chip ${status === 'RESOLVED' ? 'chip-ok' : 'chip-warn'}`}>
                            {status}
                          </span>
                        </td>
                        <td className="mono tiny">{e.entity_type || '—'}</td>
                        <td className="tiny" style={{ whiteSpace: 'normal', maxWidth: 380 }}>
                          {e.description}
                        </td>
                        <td className={`mono tiny ${breached ? 'down' : 'muted'}`}>
                          {e.sla_due_at ? new Date(e.sla_due_at).toLocaleTimeString() : '—'}
                          {breached ? ' late' : ''}
                        </td>
                        <td>
                          {status !== 'RESOLVED' && (
                            <button className="btn btn-sm"
                              onClick={() => { setOpenId(openId === e.id ? null : e.id); setNote(null); }}>
                              {openId === e.id ? 'Close' : 'Resolve'}
                            </button>
                          )}
                        </td>
                      </tr>
                      {openId === e.id && (
                        <tr key={`${e.id}-form`}>
                          <td colSpan={8} style={{ background: 'var(--surface-2)' }}>
                            <div style={{ padding: '12px 14px', maxWidth: 620 }}>
                                {triage[e.id] && (
                                <div className="result good" style={{ marginBottom: 12 }}>
                                  <span className="code">SUGGESTED — ADVISORY ONLY</span>
                                  {triage[e.id].loading ? 'Reading the break…' : (
                                    <div style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>
                                      {triage[e.id].suggestion}
                                    </div>
                                  )}
                                  {triage[e.id].provenance && (
                                    <div className="tiny muted" style={{ marginTop: 8 }}>
                                      {triage[e.id].provenance.degraded
                                        ? 'Generated without a model — deterministic fallback.'
                                        : `${triage[e.id].provenance.provider} · ${triage[e.id].provenance.model}. Verify before acting.`}
                                    </div>
                                  )}
                                </div>
                              )}
                              {!triage[e.id] && (
                                <button className="btn btn-sm" style={{ marginBottom: 12 }}
                                  onClick={() => getTriage(e.id)}>
                                  Suggest a cause
                                </button>
                              )}
                              <label className="f">
                                <span className="lab">Action taken</span>
                                <input value={action} onChange={(ev) => setAction(ev.target.value)}
                                  placeholder="Reference data corrected; order resubmitted" />
                              </label>
                              <label className="f">
                                <span className="lab">Reason — required</span>
                                <textarea rows={2} value={reason}
                                  onChange={(ev) => setReason(ev.target.value)}
                                  placeholder="Why this break occurred and why it is now closed" />
                              </label>
                              <button className="btn btn-primary btn-sm"
                                onClick={() => resolve(e.id)} disabled={busy}>
                                Resolve and log
                              </button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
