/**
 * The lifecycle rail.
 *
 * Twelve stages from order capture to settled, drawn as a track. This is
 * the platform's central claim made visible: an order crosses every stage
 * without a human touching it, and where it stops, you can see exactly why.
 */

const STAGES = [
  ['capture', 'Capture'],
  ['enrichment', 'Enrich'],
  ['validation', 'Validate'],
  ['risk', 'Risk'],
  ['routing', 'Route'],
  ['execution', 'Execute'],
  ['fill_capture', 'Fills'],
  ['clearing', 'Clear'],
  ['position_update', 'Position'],
  ['settlement_instruction', 'Instruct'],
  ['settlement_matching', 'Match'],
  ['settlement', 'Settle'],
];

function classFor(entry) {
  if (!entry) return '';
  const s = entry.status;
  if (s === 'OK') return 'ok';
  if (s === 'REJECTED' || s === 'FAILED' || s === 'DUPLICATE') return 'bad';
  if (s === 'EXCEPTION') return 'exc';
  if (s === 'WORKING' || s === 'PENDING') return 'exc';
  return '';
}

function timeOf(entry) {
  if (!entry || !entry.at) return '';
  try {
    return new Date(entry.at).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch { return ''; }
}

export default function LifecycleRail({ lifecycle }) {
  if (!lifecycle || lifecycle.length === 0) return null;

  const byStage = {};
  lifecycle.forEach((e) => { byStage[e.stage] = e; });

  const reached = lifecycle.filter((e) => e.status === 'OK').length;
  const halted = lifecycle.find(
    (e) => ['REJECTED', 'FAILED', 'EXCEPTION', 'DUPLICATE'].includes(e.status)
  );

  return (
    <div className="life">
      <div className="split" style={{ marginBottom: 10 }}>
        <span className="chip chip-mute">
          {reached}/{STAGES.length} stages cleared
        </span>
        {halted ? (
          <span className={`chip ${halted.status === 'EXCEPTION' ? 'chip-warn' : 'chip-bad'}`}>
            halted at {halted.stage.replace(/_/g, ' ')}
          </span>
        ) : (
          <span className="chip chip-ok">straight through · no manual step</span>
        )}
      </div>

      <div className="life-track">
        {STAGES.map(([key, label], i) => {
          const entry = byStage[key];
          return (
            <div key={key} className={`life-node ${classFor(entry)}`}>
              <span className="dot" style={{ animationDelay: `${i * 45}ms` }} />
              <div className="name">{label}</div>
              <div className="at">{timeOf(entry)}</div>
            </div>
          );
        })}
      </div>

      {halted && halted.detail && (
        <div className="tiny muted" style={{ marginTop: 8, fontFamily: 'var(--mono)' }}>
          {halted.detail}
        </div>
      )}
    </div>
  );
}
