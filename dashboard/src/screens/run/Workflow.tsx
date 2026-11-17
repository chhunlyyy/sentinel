import { useEffect, useMemo, useRef, useState } from 'react';
import { calls } from '../../api/calls.ts';
import type { Workflow, WorkflowNode } from '../../api/types.ts';
import { Loaded } from '../../components/common.tsx';
import { NodeDetails } from '../../components/NodeDetails.tsx';
import { clock } from '../../format.ts';
import { Link, enc } from '../../router.tsx';
import { useApp, useResource } from '../../state/app.tsx';
import { NextBanner } from '../Run.tsx';

/** Announce task state changes through the polite live region, after the REST answer shows them. */
export function useStateAnnouncer(nodes: WorkflowNode[] | undefined) {
  const { announce } = useApp();
  const prev = useRef<Map<string, string> | null>(null);
  useEffect(() => {
    if (!nodes) return;
    const next = new Map(nodes.map((n) => [n.id, n.state]));
    if (prev.current) {
      for (const n of nodes) {
        const before = prev.current.get(n.id);
        if (before !== undefined && before !== n.state) announce(`${n.role} ${n.state}`);
      }
    }
    prev.current = next;
  }, [nodes, announce]);
}

/** Order nodes so that every task follows the tasks it depends on (stable by input order). */
export function topoOrder(wf: Workflow): { nodes: WorkflowNode[]; depth: Map<string, number>; deps: Map<string, string[]> } {
  const index = new Map(wf.nodes.map((n, i) => [n.id, i]));
  const deps = new Map<string, string[]>(wf.nodes.map((n) => [n.id, []]));
  for (const e of wf.edges) if (index.has(e.from) && index.has(e.to)) deps.get(e.to)!.push(e.from);
  const children = new Map<string, string[]>(wf.nodes.map((n) => [n.id, []]));
  for (const [to, froms] of deps) for (const f of froms) children.get(f)!.push(to);
  const left = new Map(wf.nodes.map((n) => [n.id, deps.get(n.id)!.length]));
  const depth = new Map<string, number>();
  const ready = wf.nodes.filter((n) => left.get(n.id) === 0).map((n) => n.id);
  ready.forEach((id) => depth.set(id, 0));
  const order: string[] = [];
  while (ready.length) {
    ready.sort((a, b) => index.get(a)! - index.get(b)!);
    const id = ready.shift()!;
    order.push(id);
    for (const c of children.get(id)!) {
      depth.set(c, Math.max(depth.get(c) ?? 0, (depth.get(id) ?? 0) + 1));
      left.set(c, left.get(c)! - 1);
      if (left.get(c) === 0) ready.push(c);
    }
  }
  for (const n of wf.nodes) if (!order.includes(n.id)) order.push(n.id); // a cycle should not happen; keep the node visible
  const byId = new Map(wf.nodes.map((n) => [n.id, n]));
  return { nodes: order.map((id) => byId.get(id)!), depth, deps };
}

function nodeLines(n: WorkflowNode): string[] {
  return [
    `${n.id} ${n.role}`,
    `${n.repo ?? 'no repo'} ${n.state}`,
    `${n.adapter} ${n.provider ?? 'no provider'} ${n.model ?? 'no model'} attempt ${n.attempt}`,
    `${n.started_at ? clock(n.started_at) : 'not started'} ${n.seconds !== null && n.seconds !== undefined ? `${n.seconds}s` : ''}`.trim(),
    n.retry_of ? `Retry of ${n.retry_of}` : n.error_code ? `error ${n.error_code}` : (n.label ?? ''),
  ];
}

const NW = 220;

const NH = 92;

const GX = 40;

const GY = 16;

function Graph({ wf, nodes, depth, onSelect, selected }: { wf: Workflow; nodes: WorkflowNode[]; depth: Map<string, number>; onSelect: (id: string) => void; selected: string | null }) {
  const shownIds = new Set(nodes.map((n) => n.id));
  const rowOf = new Map<string, number>();
  const counts = new Map<number, number>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    const r = counts.get(d) ?? 0;
    counts.set(d, r + 1);
    rowOf.set(n.id, r);
  }
  const pos = (id: string) => ({ x: 10 + (depth.get(id) ?? 0) * (NW + GX), y: 10 + (rowOf.get(id) ?? 0) * (NH + GY) });
  const maxD = Math.max(0, ...nodes.map((n) => depth.get(n.id) ?? 0));
  const maxR = Math.max(1, ...counts.values());
  const width = 20 + (maxD + 1) * (NW + GX);
  const height = 20 + maxR * (NH + GY);
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="graph" tabIndex={0} role="region" aria-label="Workflow graph, scrollable">
      <svg role="group" aria-label="Run workflow graph" width={width} height={height}>
        {wf.edges
          .filter((e) => shownIds.has(e.from) && shownIds.has(e.to))
          .map((e) => {
            const a = pos(e.from);
            const b = pos(e.to);
            const x1 = a.x + NW;
            const y1 = a.y + NH / 2;
            const x2 = b.x;
            const y2 = b.y + NH / 2;
            const mid = (x1 + x2) / 2;
            return <path key={`${e.from}->${e.to}`} className="edge" data-edge={`${e.from}->${e.to}`} d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`} />;
          })}
        {nodes.map((n) => {
          const p = pos(n.id);
          return (
            <g
              key={n.id}
              data-testid={`node-${n.id}`}
              role="button"
              tabIndex={0}
              aria-pressed={selected === n.id}
              onClick={() => onSelect(n.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(n.id);
                }
              }}
            >
              <rect className="node-box" x={p.x} y={p.y} width={NW} height={NH} rx={6} />
              {nodeLines(n).map((line, i) => (
                <text key={i} x={p.x + 8} y={p.y + 16 + i * 16}>
                  {line}
                </text>
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function WorkflowTab({ pid, slug, base }: { pid: string; slug: string; base: string }) {
  const res = useResource<Workflow>(`workflow-${pid}-${slug}`, (c) => calls.workflow(c, slug, pid), { project: pid, run: slug });
  useStateAnnouncer(res.data?.nodes);
  const [view, setView] = useState<'graph' | 'list'>('graph');
  const [state, setState] = useState('');
  const [role, setRole] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const topo = useMemo(() => (res.data ? topoOrder(res.data) : null), [res.data]);
  return (
    <>
      <h2>Workflow</h2>
      <Loaded res={res}>
        {(wf) => {
          if (wf.nodes.length === 0) {
            return (
              <>
                <p>No tasks yet</p>
                <NextBanner pid={pid} slug={slug} base={base} />
              </>
            );
          }
          const t = topo!;
          const states = Array.from(new Set(wf.nodes.map((n) => n.state))).sort();
          const roles = Array.from(new Set(wf.nodes.map((n) => n.role))).sort();
          const shown = t.nodes.filter((n) => (!state || n.state === state) && (!role || n.role === role));
          const sel = wf.nodes.find((n) => n.id === selected) ?? null;
          return (
            <>
              <ul className="plain row" aria-label="Approval gates">
                {wf.gates.map((g) => (
                  <li key={g.gate} className="panel" data-testid={`gate-${g.gate}`}>
                    {g.gate === 'specification' ? 'Specification' : 'Gherkin'} gate: {g.state}
                    {g.version ? ` (version ${g.version})` : ''}
                  </li>
                ))}
              </ul>
              <div className="row">
                <div className="field">
                  <label htmlFor="wf-state">Filter by state</label>{' '}
                  <select id="wf-state" value={state} onChange={(e) => setState(e.target.value)}>
                    <option value="">All states</option>
                    {states.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="wf-role">Filter by role</label>{' '}
                  <select id="wf-role" value={role} onChange={(e) => setRole(e.target.value)}>
                    <option value="">All roles</option>
                    {roles.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <button type="button" className="secondary" aria-pressed={view === 'graph'} onClick={() => setView('graph')}>
                  Graph
                </button>
                <button type="button" className="secondary" aria-pressed={view === 'list'} onClick={() => setView('list')}>
                  List
                </button>
              </div>
              {view === 'graph' ? (
                <>
                  <Graph wf={wf} nodes={shown} depth={t.depth} onSelect={setSelected} selected={selected} />
                  {sel ? (
                    <div className="panel" data-testid="node-details">
                      <h3>Task {sel.id}</h3>
                      <NodeDetails node={sel} />
                      <Link to={`${base}/log/${enc(sel.id)}`}>Log of {sel.id}</Link>
                    </div>
                  ) : (
                    <p className="hint">Select a task to see its details.</p>
                  )}
                </>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {['Task', 'Role', 'Repository', 'State', 'Adapter', 'Provider', 'Model', 'Attempt', 'Started', 'Duration', 'Depends on', 'Notes', 'Log'].map((h) => (
                          <th scope="col" key={h}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((n) => {
                        const deps = t.deps.get(n.id) ?? [];
                        return (
                          <tr key={n.id} data-testid="workflow-row">
                            <th scope="row">{n.id}</th>
                            <td>{n.role}</td>
                            <td>{n.repo ?? 'none'}</td>
                            <td>{n.state}</td>
                            <td>{n.adapter}</td>
                            <td>{n.provider ?? 'Not reported'}</td>
                            <td>{n.model ?? 'Not reported'}</td>
                            <td>attempt {n.attempt}</td>
                            <td>{n.started_at ? clock(n.started_at) : 'not started'}</td>
                            <td>{n.seconds !== null && n.seconds !== undefined ? `${n.seconds}s` : 'Not reported'}</td>
                            <td>{deps.length ? `Depends on ${deps.join(', ')}` : 'No dependencies'}</td>
                            <td>
                              {n.retry_of ? `Retry of ${n.retry_of}. ` : ''}
                              {n.error_code ? `Error ${n.error_code}. ` : ''}
                              {n.label ?? ''}
                            </td>
                            <td>
                              <Link to={`${base}/log/${enc(n.id)}`}>Log</Link>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          );
        }}
      </Loaded>
    </>
  );
}

