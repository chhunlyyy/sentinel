// SVG edge layer for the neural-network canvas.
// All paths go in a single aria-hidden SVG with preserveAspectRatio="none"
// and vector-effect="non-scaling-stroke" so edges are drawn cleanly between station centres.
import type { StationState } from './types.ts';
import { stateLook, feedEdgeCls } from './look.ts';

interface EdgeLayerProps {
  /** state of each station for the selected run */
  states: Record<string, StationState>;
  /** y-positions for the N build lanes (in viewBox units) */
  buildLaneYs: number[];
  /** state of each build lane, same order as buildLaneYs (falls back to the build station state) */
  laneStates?: StationState[];
}

function ecls(states: Record<string, StationState>, id: string): string {
  const st = states[id] ?? 'todo';
  return stateLook(st).edgeCls;
}

function feed(states: Record<string, StationState>, id: string): string {
  return feedEdgeCls(states[id] ?? 'todo');
}

export function EdgeLayer({ states, buildLaneYs, laneStates }: EdgeLayerProps) {
  const lanes = buildLaneYs.length === 0 ? [250] : buildLaneYs;
  const laneState = (i: number): StationState => laneStates?.[i] ?? states.build ?? 'todo';
  const verifyState = states.verify ?? 'todo';

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 1000 560"
      preserveAspectRatio="none"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    >
      {/* Knowledge feed links — dotted blue from (470, 480) to each agent neuron */}
      {/* triage */}
      <path
        className={`floor-e ${feed(states, 'triage')}`}
        d="M470 480 C 300 480, 165 400, 165 170"
        vectorEffect="non-scaling-stroke"
      />
      {/* spec */}
      <path
        className={`floor-e ${feed(states, 'spec')}`}
        d="M470 480 C 380 480, 270 420, 270 250"
        vectorEffect="non-scaling-stroke"
      />
      {/* gherkin */}
      <path
        className={`floor-e ${feed(states, 'gherkin')}`}
        d="M470 480 C 470 400, 470 330, 470 250"
        vectorEffect="non-scaling-stroke"
      />
      {/* build lane feeds */}
      {lanes.map((y, i) => {
        const cls = feedEdgeCls(laneState(i));
        return (
          <path
            key={`feed-b${i}`}
            className={`floor-e ${cls}`}
            d={`M470 480 C 580 480, 640 ${y < 250 ? y + 50 : y - 50}, 670 ${y}`}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Main flow edges */}
      {/* intake → triage */}
      <path
        className={`floor-e ${ecls(states, 'triage')}`}
        d="M60 250 C 112 250, 112 170, 165 170"
        vectorEffect="non-scaling-stroke"
      />
      {/* triage → spec */}
      <path
        className={`floor-e ${ecls(states, 'spec')}`}
        d="M165 170 C 218 170, 218 250, 270 250"
        vectorEffect="non-scaling-stroke"
      />
      {/* spec → gate_spec */}
      <path
        className={`floor-e ${ecls(states, 'gate_spec')}`}
        d="M270 250 C 320 250, 320 170, 370 170"
        vectorEffect="non-scaling-stroke"
      />
      {/* gate_spec → gherkin */}
      <path
        className={`floor-e ${ecls(states, 'gherkin')}`}
        d="M370 170 C 420 170, 420 250, 470 250"
        vectorEffect="non-scaling-stroke"
      />
      {/* gherkin → gate_gherkin */}
      <path
        className={`floor-e ${ecls(states, 'gate_gherkin')}`}
        d="M470 250 C 518 250, 518 170, 565 170"
        vectorEffect="non-scaling-stroke"
      />
      {/* gate_gherkin → each build lane */}
      {lanes.map((y, i) => (
        <path
          key={`gb${i}`}
          className={`floor-e ${stateLook(laneState(i)).edgeCls}`}
          d={`M565 170 C 618 170, 618 ${y}, 670 ${y}`}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {/* each build lane → verify */}
      {lanes.map((y, i) => (
        <path
          key={`bv${i}`}
          className={`floor-e ${laneState(i) === 'done' && verifyState !== 'todo' ? 'floor-e-done' : ecls(states, 'verify')}`}
          d={`M670 ${y} C 722 ${y}, 722 250, 775 250`}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {/* verify → report */}
      <path
        className={`floor-e ${ecls(states, 'report')}`}
        d="M775 250 C 820 250, 820 170, 865 170"
        vectorEffect="non-scaling-stroke"
      />
      {/* report → gate_accept */}
      <path
        className={`floor-e ${ecls(states, 'gate_accept')}`}
        d="M865 170 C 908 170, 908 250, 950 250"
        vectorEffect="non-scaling-stroke"
      />
      {/* gate_accept → knowledge */}
      <path
        className={`floor-e ${ecls(states, 'knowledge')}`}
        d="M950 250 C 950 420, 640 480, 470 480"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
