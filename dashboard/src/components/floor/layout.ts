// Fixed station metadata and layout geometry for the factory floor.
// Positions are in the 1000×560 viewBox used by the neural-network canvas.
import type { StationDef } from './types.ts';

export const STATION_ORDER = [
  'intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin',
  'build', 'verify', 'report', 'gate_accept', 'knowledge',
] as const;

export const STATIONS: StationDef[] = [
  {
    id: 'intake', name: 'Intake', glyph: 'In', kind: 'engine', x: 60, y: 250,
    does: 'Records the request, picks the repos and opens a run.',
    knowledgeText: '—',
  },
  {
    id: 'triage', name: 'Triage', glyph: 'Tr', kind: 'agent', x: 165, y: 170,
    does: 'Sizes the task from seven risk factors and picks how much rigor it needs.',
    knowledgeText: 'Repo summary, module summaries for its write scope, invariants, 5 recent related changes',
  },
  {
    id: 'spec', name: 'Specification', glyph: 'Sp', kind: 'agent', x: 270, y: 250,
    does: 'Writes the spec: requirements, acceptance criteria, risks, QA steps.',
    knowledgeText: 'Repo summary, module summaries for its write scope, invariants, 5 recent related changes',
  },
  {
    id: 'gate_spec', name: 'You approve spec', glyph: 'You', kind: 'gate', x: 370, y: 170,
    does: 'Nothing is built until you approve the specification by its hash.',
    knowledgeText: 'The report shows which knowledge the agents used',
  },
  {
    id: 'gherkin', name: 'Scenarios', glyph: 'Gk', kind: 'agent', x: 470, y: 250,
    does: 'Turns the spec into Gherkin scenarios, one per behavior and edge case.',
    knowledgeText: 'Repo summary, module summaries for its write scope, invariants, 5 recent related changes',
  },
  {
    id: 'gate_gherkin', name: 'You approve scenarios', glyph: 'You', kind: 'gate', x: 565, y: 170,
    does: 'You confirm the scenarios that the tests will prove.',
    knowledgeText: 'The report shows which knowledge the agents used',
  },
  {
    id: 'build', name: 'Build', glyph: 'Bu', kind: 'agent', x: 670, y: 250,
    does: 'One behavior per lane: Red (failing test), Green (make it pass), Refactor.',
    knowledgeText: 'Repo summary, module summaries for its write scope, invariants, 5 recent related changes',
  },
  {
    id: 'verify', name: 'Verify', glyph: 'Ve', kind: 'engine', x: 775, y: 250,
    does: 'Runs tests, lint, typecheck and build itself. An agent\'s claim is never evidence.',
    knowledgeText: '—',
  },
  {
    id: 'report', name: 'Report', glyph: 'Re', kind: 'engine', x: 865, y: 170,
    does: 'Writes the report: evidence, trace from requirement to code, findings.',
    knowledgeText: '—',
  },
  {
    id: 'gate_accept', name: 'You accept', glyph: 'You', kind: 'gate', x: 950, y: 250,
    does: 'You read the report and accept or reject the result.',
    knowledgeText: 'The report shows which knowledge the agents used',
  },
  {
    id: 'knowledge', name: 'Knowledge', glyph: 'Kb', kind: 'engine', x: 470, y: 480,
    does: 'Records the change in the shared knowledge base and feeds summaries, invariants and past changes to every agent.',
    knowledgeText: 'Writes the record; summaries by a cheap model',
  },
];

export function stationById(id: string): StationDef | undefined {
  return STATIONS.find((s) => s.id === id);
}

const MAX_LANES = 6;

/** A lane's name on the floor: the behavior, without the feature file path and the `Rule`/`Scenario` keyword
 * (`features/a.feature :: Rule Self-requests escalate` → `Self-requests escalate`). The full name stays in the side panel. */
export function laneLabel(name: string): string {
  const behavior = name.includes('::') ? name.slice(name.lastIndexOf('::') + 2) : name;
  return behavior.trim().replace(/^(Rule|Scenario Outline|Scenario|Feature):?\s+/i, '') || name.trim();
}

export function buildLanePositions(n: number): Array<{ x: number; y: number }> {
  const count = Math.min(n, MAX_LANES);
  if (count <= 1) return [{ x: 670, y: 250 }];
  if (count === 2) return [{ x: 670, y: 170 }, { x: 670, y: 330 }];
  if (count === 3) return [{ x: 670, y: 90 }, { x: 670, y: 250 }, { x: 670, y: 410 }];
  const minY = 60;
  const maxY = 470;
  const step = (maxY - minY) / (count - 1);
  return Array.from({ length: count }, (_, i) => ({
    x: 670,
    y: Math.round(minY + step * i),
  }));
}

export { MAX_LANES };
