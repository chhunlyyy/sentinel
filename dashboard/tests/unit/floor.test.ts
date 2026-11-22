import { describe, expect, test } from 'vitest';
import { floorSnapshot, laneState } from '../../src/components/floor/adapt.ts';
import { buildLanePositions, stationById, STATIONS, MAX_LANES } from '../../src/components/floor/layout.ts';
import { stateLook, feedEdgeCls } from '../../src/components/floor/look.ts';
import { stationsOf } from '../../src/screens/Floor.tsx';
import { parseSpecDoc } from '../../src/screens/Approvals.tsx';
import type * as W from '../../src/api/wire.ts';

const SAMPLE_WIRE_FACTORY: W.WFactory = {
  project: 'digital-hr',
  factory_paused: false,
  who: { triage: { role: 'triage', runner: 'agy', model: 'gemini-3.8-flash' }, build: { role: 'coder', runner: 'claude', model: null } },
  activity: [{ at: '2026-11-21T10:45:14.000000Z', run: 'leave-balance', station: 'build', text: 'green' }],
  generated_at: '2026-11-21T10:15:02.123456Z',
  stations: [
    'intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin',
    'build', 'verify', 'report', 'gate_accept', 'knowledge',
  ],
  limits: {
    driver: 'engine',
    max_tasks_per_project: 2,
    max_agents: 4,
    running_in_project: 2,
    running_total: 3,
  },
  runs: [
    {
      slug: 'leave-balance',
      title: 'Show the remaining leave days on the home page',
      type: 'feature',
      driver: 'engine',
      paused: false,
      state: 'EXECUTING',
      tier: 3,
      station: 'build',
      stations: {
        intake: 'done', triage: 'done', spec: 'done', gate_spec: 'done',
        gherkin: 'done', gate_gherkin: 'done',
        build: 'working', verify: 'next', report: 'todo', gate_accept: 'todo', knowledge: 'todo',
      },
      next_station: 'verify',
      agents: {
        build: [
          {
            task: 't-0123456789ab',
            role: 'tdd_green',
            runner: 'claude',
            model: 'sonnet',
            adapter: 'cli',
            started_at: '2026-11-21T10:12:40.000000Z',
          },
        ],
      },
      lanes: [
        {
          cycle: 'c-0123456789ab',
          name: 'Remaining days show',
          repo: 'backend',
          state: 'GREEN_RUNNING',
          red: 'done',
          green: 'working',
          refactor: 'todo',
        },
      ],
      attention: null,
      pending_notes: 0,
      created_at: '2026-11-21T09:58:00.000000Z',
      updated_at: '2026-11-21T10:12:40.000000Z',
    },
  ],
  queue: [
    {
      slug: 'payroll-export',
      title: 'Export payroll as CSV',
      position: 1,
      reason: 'the project limit of 2 running tasks is reached',
    },
  ],
};

describe('factory floor snapshot-to-view mapping', () => {
  test('maps project, limits, and queue items', () => {
    const snap = floorSnapshot(SAMPLE_WIRE_FACTORY);
    expect(snap.project).toBe('digital-hr');
    expect(snap.generatedAt).toBe('2026-11-21T10:15:02.123456Z');
    expect(snap.limits).toEqual({
      driver: 'engine',
      maxTasksPerProject: 2,
      maxAgents: 4,
      runningInProject: 2,
      runningTotal: 3,
    });
    expect(snap.queue).toHaveLength(1);
    expect(snap.queue[0]).toEqual({
      slug: 'payroll-export',
      title: 'Export payroll as CSV',
      position: 1,
      reason: 'the project limit of 2 running tasks is reached',
    });
  });

  test('maps run fields, initials, and colors', () => {
    const snap = floorSnapshot(SAMPLE_WIRE_FACTORY);
    expect(snap.runs).toHaveLength(1);
    const r = snap.runs[0];
    expect(r.slug).toBe('leave-balance');
    expect(r.short).toBe('LB');
    expect(r.paused).toBe(false);
    expect(r.station).toBe('build');
    expect(r.stateLabel).toBe('Working');
    expect(r.stationLabel).toBe('Build');
    expect(r.nextStation).toBe('verify');
    expect(r.color).toBeDefined();
  });

  test('maps agents per station', () => {
    const snap = floorSnapshot(SAMPLE_WIRE_FACTORY);
    const r = snap.runs[0];
    expect(r.agents.build).toBeDefined();
    expect(r.agents.build).toHaveLength(1);
    expect(r.agents.build[0]).toEqual({
      task: 't-0123456789ab',
      role: 'tdd_green',
      runner: 'claude',
      model: 'sonnet',
      adapter: 'cli',
      startedAt: '2026-11-21T10:12:40.000000Z',
    });
  });

  test('maps station_tasks per station', () => {
    const wireWithStationTasks = {
      ...SAMPLE_WIRE_FACTORY,
      runs: [
        {
          ...SAMPLE_WIRE_FACTORY.runs[0],
          station_tasks: {
            build: [
              {
                id: 't-0123456789ab',
                role: 'tdd_green',
                state: 'RUNNING',
                started_at: '2026-11-21T10:12:40.000000Z',
                finished_at: null,
              },
            ],
          },
        },
      ],
    };
    const snap = floorSnapshot(wireWithStationTasks);
    const r = snap.runs[0];
    expect(r.station_tasks?.build).toBeDefined();
    expect(r.station_tasks?.build[0]).toEqual({
      id: 't-0123456789ab',
      role: 'tdd_green',
      state: 'RUNNING',
      startedAt: '2026-11-21T10:12:40.000000Z',
      finishedAt: null,
    });
  });

  test('maps lanes and their TDD phase states', () => {
    const snap = floorSnapshot(SAMPLE_WIRE_FACTORY);
    const r = snap.runs[0];
    expect(r.lanes).toHaveLength(1);
    expect(r.lanes[0]).toEqual({
      cycle: 'c-0123456789ab',
      name: 'Remaining days show',
      repo: 'backend',
      state: 'GREEN_RUNNING',
      red: 'done',
      green: 'working',
      refactor: 'todo',
    });
  });

  test('stationsOf preserves states when not paused', () => {
    const snap = floorSnapshot(SAMPLE_WIRE_FACTORY);
    const r = snap.runs[0];
    const states = stationsOf(r);
    expect(states.build).toBe('working');
    expect(states.intake).toBe('done');
    expect(states.verify).toBe('next');
    expect(states.report).toBe('todo');
  });

  test('stationsOf maps working to paused when run is paused', () => {
    const wirePaused: W.WFactory = {
      ...SAMPLE_WIRE_FACTORY,
      runs: [
        {
          ...SAMPLE_WIRE_FACTORY.runs[0],
          paused: true,
        },
      ],
    };
    const snap = floorSnapshot(wirePaused);
    const r = snap.runs[0];
    expect(r.stateLabel).toBe('Paused');
    const states = stationsOf(r);
    expect(states.build).toBe('paused');
    expect(states.intake).toBe('done');
  });
});

describe('station look and edge styling', () => {
  test('returns correct edge classes for each state', () => {
    expect(stateLook('done').edgeCls).toBe('floor-e-done');
    expect(stateLook('working').edgeCls).toBe('floor-e-active');
    expect(stateLook('waiting').edgeCls).toBe('floor-e-wait');
    expect(stateLook('paused').edgeCls).toBe('floor-e-pause');
    expect(stateLook('queued').edgeCls).toBe('floor-e-todo');
    expect(stateLook('next').edgeCls).toBe('floor-e-todo');
    expect(stateLook('todo').edgeCls).toBe('floor-e-todo');
  });

  test('feedEdgeCls returns active class only when working', () => {
    expect(feedEdgeCls('working')).toBe('floor-e-feed-on');
    expect(feedEdgeCls('done')).toBe('floor-e-feed');
    expect(feedEdgeCls('waiting')).toBe('floor-e-feed');
    expect(feedEdgeCls('todo')).toBe('floor-e-feed');
  });

  test('live property is true for working and waiting states', () => {
    expect(stateLook('working').live).toBe(true);
    expect(stateLook('waiting').live).toBe(true);
    expect(stateLook('done').live).toBe(false);
    expect(stateLook('paused').live).toBe(false);
    expect(stateLook('todo').live).toBe(false);
  });
});

describe('build lane layout', () => {
  test('0 or 1 lane places neuron in the center at y=250', () => {
    expect(buildLanePositions(0)).toEqual([{ x: 670, y: 250 }]);
    expect(buildLanePositions(1)).toEqual([{ x: 670, y: 250 }]);
  });

  test('2 lanes place neurons symmetrically at y=170 and y=330', () => {
    expect(buildLanePositions(2)).toEqual([
      { x: 670, y: 170 },
      { x: 670, y: 330 },
    ]);
  });

  test('3 lanes match mockup positions: 90, 250, 410', () => {
    expect(buildLanePositions(3)).toEqual([
      { x: 670, y: 90 },
      { x: 670, y: 250 },
      { x: 670, y: 410 },
    ]);
  });

  test('caps drawn lanes at MAX_LANES (6)', () => {
    const eight = buildLanePositions(8);
    expect(eight).toHaveLength(MAX_LANES);
    expect(eight[0].y).toBe(90);
    expect(eight[eight.length - 1].y).toBe(410);
  });
});

describe('station metadata', () => {
  test('all 11 fixed stations are defined in order', () => {
    expect(STATIONS).toHaveLength(11);
    const ids = STATIONS.map((s) => s.id);
    expect(ids).toEqual([
      'intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin',
      'build', 'verify', 'report', 'gate_accept', 'knowledge',
    ]);
  });

  test('stationById finds existing station and returns undefined for unknown', () => {
    expect(stationById('spec')?.name).toBe('Specification');
    expect(stationById('gate_spec')?.kind).toBe('gate');
    expect(stationById('unknown')).toBeUndefined();
  });
});

describe('floor snapshot additions and lanes', () => {
  test('adapts factory_paused, who and activity', () => {
    const snap = floorSnapshot({ ...SAMPLE_WIRE_FACTORY, factory_paused: true });
    expect(snap.factoryPaused).toBe(true);
    expect(snap.who.triage).toEqual({ role: 'triage', runner: 'agy', model: 'gemini-3.8-flash' });
    expect(snap.who.build.model).toBeNull();
    expect(snap.activity[0]).toEqual({ at: '2026-11-21T10:45:14.000000Z', run: 'leave-balance', station: 'build', text: 'green' });
  });

  test('missing who and activity fall back to empty', () => {
    const w = { ...SAMPLE_WIRE_FACTORY } as Partial<W.WFactory>;
    delete w.who;
    delete w.activity;
    delete w.factory_paused;
    const snap = floorSnapshot(w as W.WFactory);
    expect(snap.who).toEqual({});
    expect(snap.activity).toEqual([]);
    expect(snap.factoryPaused).toBe(false);
  });

  test('laneState: done, working, queued', () => {
    expect(laneState({ red: 'done', green: 'done', refactor: 'done' }, false)).toBe('done');
    expect(laneState({ red: 'done', green: 'working', refactor: 'todo' }, false)).toBe('working');
    expect(laneState({ red: 'done', green: 'working', refactor: 'todo' }, true)).toBe('paused');
    expect(laneState({ red: 'todo', green: 'todo', refactor: 'todo' }, false)).toBe('queued');
  });

  test('whereLabel names the behavior when build fans out', () => {
    const w = structuredClone(SAMPLE_WIRE_FACTORY);
    const base = w.runs[0].lanes[0];
    w.runs[0].lanes = [
      { ...base, red: 'done', green: 'done', refactor: 'done' },
      { ...base, red: 'done', green: 'working', refactor: 'todo' },
      { ...base, red: 'todo', green: 'todo', refactor: 'todo' },
    ];
    expect(floorSnapshot(w).runs[0].whereLabel).toBe('Build \u00b7 behavior 2 of 3');
  });
});

describe('usage limit and routing problems', () => {
  const limited = (): W.WFactory => {
    const w = JSON.parse(JSON.stringify(SAMPLE_WIRE_FACTORY)) as W.WFactory;
    const run = w.runs[0];
    run.station = 'triage';
    run.stations = { ...run.stations, triage: 'limit', build: 'todo' };
    run.lanes = [];
    run.agents = {};
    run.limit = { station: 'triage', task: 't-1', role: 'triage', runner: 'claude', retry_at: '2026-11-21T14:05:00.000000Z', reason: 'usage limit reached' };
    w.routing = { problems: ['triage routes to the native adapter'] };
    return w;
  };

  test('a run waiting for a limit gets a paused look and a retry time, not a failed one', () => {
    const snap = floorSnapshot(limited());
    const run = snap.runs[0];
    expect(run.stations.triage).toBe('limit');
    expect(run.whereLabel).toMatch(/^Waiting for usage limit · retries \d\d:\d\d$/);
    expect(run.stateLabel).toBe(run.whereLabel);
    expect(run.limit).toEqual({ task: 't-1', role: 'triage', runner: 'claude', retryAt: '2026-11-21T14:05:00.000000Z', reason: 'usage limit reached' });
    const look = stateLook('limit');
    expect(look.label).toBe('Waiting for usage limit');
    expect(look.ring).toBe(stateLook('paused').ring);
    expect(look.live).toBe(false);
    expect(stationsOf(run).triage).toBe('limit');
  });

  test('routing problems come through, and are empty when the snapshot has none', () => {
    expect(floorSnapshot(limited()).routingProblems).toEqual(['triage routes to the native adapter']);
    expect(floorSnapshot(SAMPLE_WIRE_FACTORY).routingProblems).toEqual([]);
  });

  test('a build lane that works while its task waits for a limit shows the limit', () => {
    expect(laneState({ red: 'done', green: 'working', refactor: 'todo' }, false, true)).toBe('limit');
    expect(laneState({ red: 'done', green: 'working', refactor: 'todo' }, true, true)).toBe('paused');
  });

  test('parseSpecDoc parses # title as doc title and ## headings as sections without Overview', () => {
    const markdown = `# Self-request escalation: push to parent

## Problem statement
When the approver of a step submits a request...

## Objectives
A requester never decides their own step.
`;
    const doc = parseSpecDoc(markdown);
    expect(doc.title).toBe('Self-request escalation: push to parent');
    expect(doc.sections).toHaveLength(2);
    expect(doc.sections[0].title).toBe('Problem statement');
    expect(doc.sections[0].content).toContain('When the approver');
    expect(doc.sections[1].title).toBe('Objectives');
    expect(doc.sections.some((s) => s.title === 'Overview')).toBe(false);
  });
});

