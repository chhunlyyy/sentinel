// NeuronButton: a single station node rendered as an accessible <button>.
// Agents = circle, engines = rounded square, human gates = diamond (rotated square).
import type { StationDef, StationKind, StationState } from './types.ts';
import { stateLook } from './look.ts';

interface TaskDot {
  short: string;
  color: string;
  title: string;
}

interface NeuronButtonProps {
  station: StationDef;
  state: StationState;
  taskDots: TaskDot[];
  /** second label line: `runner · model` for agents, `engine`, or `you` for gates */
  sub: string;
  selected: boolean;
  onClick: () => void;
}

function kindClass(kind: StationKind): string {
  if (kind === 'agent') return 'floor-neuron floor-neuron-agent';
  if (kind === 'gate') return 'floor-neuron floor-neuron-gate';
  return 'floor-neuron floor-neuron-engine';
}

export function NeuronButton({ station, state, taskDots, sub, selected, onClick }: NeuronButtonProps) {
  const L = stateLook(state);
  const isGate = station.kind === 'gate';
  const ring = isGate && (state === 'todo' || state === 'next') ? 'var(--floor-gate-idle-ring)' : L.ring;
  const baseGlow = L.glow === 'none' ? '' : L.glow;
  const selExtra = selected
    ? (baseGlow ? `, 0 0 0 3px rgba(230, 234, 238, 0.4)` : '0 0 0 3px rgba(230, 234, 238, 0.3)')
    : '';
  const glow = baseGlow ? baseGlow + selExtra : (selExtra || 'none');

  const ariaLabel = `${station.name}: ${L.label}`;

  // percentages in the 1000×560 viewBox
  const left = (station.x / 10).toFixed(1) + '%';
  const top = (station.y / 5.6).toFixed(1) + '%';

  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        transform: 'translate(-50%, -50%)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        width: 120,
      }}
    >
      <div style={{ position: 'relative', width: 60, height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {/* spinning dashed ring on live neurons */}
        {L.live && (
          <span
            aria-hidden="true"
            className="floor-spin"
            style={{
              position: 'absolute',
              inset: -9,
              borderRadius: '50%',
              border: `1.5px dashed ${ring}`,
              opacity: 0.8,
              pointerEvents: 'none',
            }}
          />
        )}
        <button
          type="button"
          onClick={onClick}
          aria-label={ariaLabel}
          aria-pressed={selected}
          className={`${kindClass(station.kind)} ${L.animCls}`}
          style={{
            borderColor: ring,
            background: L.fill,
            boxShadow: glow,
            color: L.ink,
          }}
        >
          <span className="floor-neuron-label" style={{ display: 'block' }}>
            {station.glyph}
          </span>
        </button>
        {/* task dots in top-right corner */}
        {taskDots.length > 0 && (
          <div
            style={{ position: 'absolute', top: -6, right: -14, display: 'flex', gap: 2, pointerEvents: 'none' }}
            aria-hidden="true"
          >
            {taskDots.map((dot, i) => (
              <span
                key={i}
                title={dot.title}
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  border: '2px solid #0E1419',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontFamily: 'ui-monospace, monospace',
                  fontSize: 9,
                  background: dot.color,
                  color: '#0B0F13',
                  fontWeight: 600,
                }}
              >
                {dot.short}
              </span>
            ))}
          </div>
        )}
      </div>
      {/* station name + sub-label sit on a chip so edges running behind never cross the text */}
      <span className="floor-label">
        <span className="floor-label-name" style={{ color: L.labelColor }}>{station.name}</span>
        <span className="floor-label-sub">{sub}</span>
      </span>
    </div>
  );
}
