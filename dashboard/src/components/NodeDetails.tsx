import type { WorkflowNode } from '../api/types.ts';
import { formatTime } from '../format.ts';

function Field({ name, label, value, reason, suffix }: { name: string; label: string; value: unknown; reason?: string; suffix?: string }) {
  const missing = value === null || value === undefined;
  return (
    <div data-testid={`field-${name}`}>
      <dt>{label}</dt>
      <dd>
        {missing ? (
          <>
            <span>Not reported</span>
            {reason ? <span className="hint"> ({reason})</span> : null}
          </>
        ) : (
          <span>
            {String(value)}
            {suffix ?? ''}
          </span>
        )}
      </dd>
    </div>
  );
}

export function NodeDetails({ node }: { node: WorkflowNode }) {
  const r = node.reasons ?? {};
  return (
    <dl className="kv" data-testid="node-details-list">
      <Field name="id" label="Task" value={node.id} />
      <Field name="role" label="Role" value={node.role} />
      <Field name="repo" label="Repository" value={node.repo} />
      <Field name="state" label="State" value={node.state} />
      <Field name="adapter" label="Adapter" value={node.adapter} />
      <Field name="provider" label="Provider" value={node.provider} reason={r.provider} />
      <Field name="model" label="Model" value={node.model} reason={r.model} />
      <Field name="attempt" label="Attempt" value={node.attempt} />
      <Field name="started_at" label="Started" value={node.started_at ? formatTime(node.started_at) : null} reason={r.started_at} />
      <Field name="seconds" label="Duration" value={node.seconds} reason={r.seconds} suffix="s" />
      <Field name="tokens" label="Tokens" value={node.tokens} reason={r.tokens} />
      <Field name="cost" label="Cost" value={node.cost} reason={r.cost} />
      {node.retry_of ? <Field name="retry_of" label="Retry of" value={node.retry_of} /> : null}
      {node.error_code ? <Field name="error_code" label="Error" value={node.error_code} /> : null}
    </dl>
  );
}
