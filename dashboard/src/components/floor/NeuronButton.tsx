// NeuronButton: a single station node rendered as an accessible <button>.
import type { StationDef, StationState } from './types.ts';
import { stateLook, HUES, type StationIconKey } from './look.ts';
import { StationIcon, getStationIconKey } from './StationIcon.tsx';

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
  /** one-line name with an ellipsis (build lanes stacked in a column) */
  compact?: boolean;
  selected: boolean;
  onClick: () => void;
}

export function NeuronButton({ station, state, taskDots, sub, selected, onClick, compact = false }: NeuronButtonProps) {
  const L = stateLook(state);
  const isGate = station.kind === 'gate';
  const iconKey: StationIconKey = getStationIconKey(station.id, station.kind);
  const c = HUES[iconKey] ?? ['#5A9BFF', '#2B4FD8'];

  const isWorking = state === 'working';
  const isWaiting = state === 'waiting';
  const isDone = state === 'done';
  const isTodo = state === 'todo' || state === 'next' || state === 'queued';
  const isPaused = state === 'paused';
  const isLimit = state === 'limit';

  const ariaLabel = `${station.name}: ${L.label}`;

  // percentages in the 1000×560 viewBox
  const left = (station.x / 10).toFixed(1) + '%';
  const top = (station.y / 5.6).toFixed(1) + '%';

  // Ring configuration
  const ringRadius = isGate ? 22 : '50%';
  let ringCls = '';
  let ringStyle: React.CSSProperties = {
    position: 'absolute',
    inset: -6,
    borderRadius: ringRadius,
    pointerEvents: 'none',
  };

  if (isWorking) {
    ringCls = 'spin';
    ringStyle = {
      ...ringStyle,
      background: 'conic-gradient(from 0deg, #4FD1C1, rgba(79, 209, 193, 0) 40%, #9DB4FF 70%, #4FD1C1)',
      WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px))',
      mask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px))',
    };
  } else if (isWaiting) {
    ringCls = 'breathe';
    ringStyle = {
      ...ringStyle,
      border: '2.5px solid #F5B547',
      boxShadow: '0 0 22px rgba(245, 181, 71, 0.55)',
    };
  } else if (isPaused) {
    ringStyle = {
      ...ringStyle,
      border: '2.5px solid #8A93AB',
    };
  } else if (isLimit) {
    ringStyle = {
      ...ringStyle,
      border: '2.5px solid #F5B547',
    };
  } else if (selected) {
    ringStyle = {
      ...ringStyle,
      border: '2px solid #9DB4FF',
    };
  } else {
    ringStyle = {
      ...ringStyle,
      display: 'none',
    };
  }

  // Tile configuration
  const tileRadius = isGate ? 18 : '50%';
  const tileFilter = isDone
    ? 'saturate(0.75)'
    : isTodo
    ? 'grayscale(0.9) brightness(0.55)'
    : undefined;
  const tileOpacity = isTodo ? 0.8 : 1;

  // Build lane number badge
  let laneNum: number | undefined;
  if (station.id.startsWith('build-')) {
    laneNum = station.laneIdx !== undefined ? station.laneIdx + 1 : parseInt(station.id.slice(6), 10) + 1;
  } else if (station.id === 'build' && station.laneIdx !== undefined && station.glyph?.startsWith('B')) {
    laneNum = station.laneIdx + 1;
  }

  // Corner badge / dot
  let dotBg = '';
  let dotKind = '';
  let dotContent: React.ReactNode = null;
  if (isDone) {
    dotBg = '#5BE37D';
    dotKind = 'done';
    dotContent = (
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#0B2B18" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M2.5 6.3l2.2 2.2 4.8-4.9" />
      </svg>
    );
  } else if (isWaiting) {
    dotBg = '#F5B547';
    dotKind = 'waiting';
    dotContent = (
      <span style={{ font: '800 11px Inter, system-ui, sans-serif', color: '#2A1A02', lineHeight: 1 }} aria-hidden="true">
        !
      </span>
    );
  } else if (isWorking) {
    dotBg = '#4FD1C1';
    dotKind = 'working';
    dotContent = (
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#062420' }} aria-hidden="true" />
    );
  } else if (isPaused || isLimit) {
    dotBg = isLimit ? '#F5B547' : '#8A93AB';
    dotKind = isLimit ? 'limit' : 'paused';
    dotContent = (
      <svg width="10" height="10" viewBox="0 0 12 12" fill="#0B0F13" aria-hidden="true">
        <rect x="3" y="2.5" width="2" height="7" rx="0.6" />
        <rect x="7" y="2.5" width="2" height="7" rx="0.6" />
      </svg>
    );
  }

  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        // anchored by the tile centre with margins, not a transform: a transform would make each station its own
        // stacking context, and a neighbour's label chip could then cover this tile
        marginLeft: -60,
        marginTop: -33,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        width: 120,
      }}
    >
      <div style={{ position: 'relative', zIndex: 2, width: 66, height: 66, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <button
          type="button"
          onClick={onClick}
          aria-label={ariaLabel}
          aria-pressed={selected}
          className="floor-neuron"
          style={{
            position: 'relative',
            width: 66,
            height: 66,
            display: 'block',
            background: 'transparent',
            border: 0,
            padding: 0,
            cursor: 'pointer',
            borderRadius: isGate ? 18 : '50%',
            outline: 'none',
          }}
        >
          {/* Ring */}
          <span
            aria-hidden="true"
            className={ringCls}
            style={ringStyle}
          />

          {/* Dedicated selection ring when selected and active */}
          {selected && (isWorking || isWaiting || isPaused || isLimit) && (
            <span
              aria-hidden="true"
              style={{
                position: 'absolute',
                inset: -10,
                borderRadius: isGate ? 26 : '50%',
                border: '2px solid #9DB4FF',
                pointerEvents: 'none',
              }}
            />
          )}

          {/* Tile */}
          <span
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: tileRadius,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              background: `linear-gradient(145deg, ${c[0]}, ${c[1]})`,
              boxShadow: `0 8px 18px -6px ${c[1]}AA, inset 0 -3px 6px rgba(0, 0, 0, 0.25)`,
              filter: tileFilter,
              opacity: tileOpacity,
            }}
          >
            {/* Top shine */}
            <span
              aria-hidden="true"
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: 'inherit',
                background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.28), rgba(255, 255, 255, 0) 48%)',
                pointerEvents: 'none',
              }}
            />
            {/* Two-tone white icon */}
            <StationIcon name={iconKey} />
          </span>

          {/* Status badge / corner dot */}
          {dotContent && (
            <span
              aria-hidden="true"
              data-badge={dotKind}
              style={{
                position: 'absolute',
                right: -4,
                bottom: -4,
                width: 20,
                height: 20,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: dotBg,
                border: '3px solid #0E1419',
                zIndex: 3,
              }}
            >
              {dotContent}
            </span>
          )}
        </button>

        {/* Build lane top-left number badge (placed as sibling with pointerEvents: 'none' to avoid WCAG 2.5.3 label-content mismatch) */}
        {laneNum !== undefined && (
          <span
            aria-hidden="true"
            className="floor-lane-num"
            data-lane-num={laneNum}
            style={{
              position: 'absolute',
              top: -4,
              left: -4,
              width: 20,
              height: 20,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: '#141A21',
              border: '3px solid #0E1419',
              color: '#E6EAEE',
              fontSize: 10,
              fontWeight: 700,
              fontFamily: 'Inter, system-ui, sans-serif',
              zIndex: 3,
              pointerEvents: 'none',
            }}
          >
            {laneNum}
          </span>
        )}

        {/* Task dots in top-right corner */}
        {taskDots.length > 0 && (
          <div
            style={{ position: 'absolute', top: -6, right: -14, display: 'flex', gap: 2, pointerEvents: 'none', zIndex: 4 }}
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
      <span className={compact ? 'floor-label floor-label-compact' : 'floor-label'}>
        <span className="floor-label-name" style={{ color: L.labelColor }} title={compact ? station.name : undefined}>{station.name}</span>
        {sub ? <span className="floor-label-sub">{sub}</span> : null}
      </span>
    </div>
  );
}
