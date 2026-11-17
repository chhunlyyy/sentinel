import type { ItemStatus, Readiness, ReadinessItem, ReadinessState } from '../api/types.ts';
import { formatTime } from '../format.ts';
import { StatusChip } from './common.tsx';

export const READINESS_LABEL: Record<ReadinessState, string> = {
  ready: 'Ready',
  ready_with_warnings: 'Ready with warnings',
  needs_configuration: 'Needs configuration',
  invalid_configuration: 'Invalid configuration',
  connection_unavailable: 'Connection unavailable',
};

/** An item is shown as validated only when the API says an executed check passed. */
export function itemLabel(status: ItemStatus | string): string {
  switch (status) {
    case 'passed':
      return 'Validated';
    case 'failed':
      return 'Failed';
    case 'warning':
      return 'Warning';
    case 'not_configured':
      return 'Not configured';
    case 'unreachable':
      return 'Not reachable';
    default:
      return 'Not checked';
  }
}

function kindOf(status: string): 'ok' | 'warn' | 'fail' | 'none' {
  if (status === 'passed') return 'ok';
  if (status === 'warning' || status === 'not_configured') return 'warn';
  if (status === 'failed' || status === 'unreachable') return 'fail';
  return 'none';
}

function ItemText({ item }: { item: ReadinessItem }) {
  return (
    <>
      <strong>{item.id}</strong>
      {item.repo ? <span> of {item.repo}</span> : null}
      {item.path ? <span> at <code>{item.path}</code></span> : null}
      {item.message ? <span>: {item.message}</span> : null}
      {item.fix ? <div>Fix: <code>{item.fix}</code></div> : null}
    </>
  );
}

export function ReadinessPanel({ readiness }: { readiness: Readiness }) {
  const problems = readiness.items.filter((i) => i.status !== 'passed' && i.status !== 'not_checked' && i.status !== 'unknown');
  return (
    <div className="panel" data-testid="readiness-panel">
      <p>
        <strong data-testid="readiness-state">{READINESS_LABEL[readiness.state] ?? 'Not checked'}</strong>
        {readiness.workflow ? <span className="hint"> for workflow {readiness.workflow}</span> : null}
        <span className="hint"> (checked {formatTime(readiness.checked_at)})</span>
      </p>
      {problems.length ? (
        <ul className="plain" data-testid="readiness-problems">
          {problems.map((i) => (
            <li key={`${i.id}-${i.repo ?? ''}`}>
              <StatusChip kind={kindOf(i.status)} label={itemLabel(i.status)} /> <ItemText item={i} />
            </li>
          ))}
        </ul>
      ) : null}
      {readiness.items.length ? (
        <details>
          <summary>All readiness items</summary>
          <ul className="plain" data-testid="readiness-items">
            {readiness.items.map((i) => (
              <li key={`${i.id}-${i.repo ?? ''}`}>
                <strong>{i.id}{i.repo ? ` (${i.repo})` : ''}</strong>: <span data-testid="item-status">{itemLabel(i.status)}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function readinessAllowsTasks(state: ReadinessState): boolean {
  return state === 'ready' || state === 'ready_with_warnings';
}
