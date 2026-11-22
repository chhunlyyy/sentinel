import { useId, useState, type ReactNode } from 'react';
import { calls } from '../api/calls.ts';
import type * as W from '../api/wire.ts';
import { costLabel, duration, isNull, money, percent } from '../analytics.ts';
import { Loaded } from '../components/common.tsx';
import { useResource } from '../state/app.tsx';

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function validDay(text: string): boolean {
  if (!DAY.test(text)) return false;
  const d = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === text;
}

/** A value that could not be computed is "Not reported" with its reason, never 0. */
function NotReported({ reason }: { reason: string }) {
  return (
    <span>
      Not reported <span className="hint">({reason})</span>
    </span>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const h = useId();
  return (
    <section aria-labelledby={h} data-testid={id}>
      <h2 id={h}>{title}</h2>
      {children}
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table>
      <thead>
        <tr>
          {head.map((h) => (
            <th key={h} scope="col">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j}>{c}</td>))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const counts = (m: Record<string, number>) => Object.entries(m).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, v] as [string, number]);

function Spread({ m }: { m: W.WSpread | W.WNullMetric }) {
  return isNull(m) ? <NotReported reason={m.reason} /> : <>{duration(m.median)} median, {duration(m.p90)} p90 ({m.count} {m.count === 1 ? 'item' : 'items'})</>;
}

function Report({ a }: { a: W.WAnalytics }) {
  const wait = a.approval_wait_seconds;
  const providers = Object.entries(a.provider_failure_rate);
  const pass = a.verification.pass_rate;
  const first = a.verification.first_attempt_pass_rate;
  const cost = a.cost;
  const total = cost.total;
  return (
    <>
      <Section id="report-runs" title="Runs">
        <Table head={['Measure', 'Value']} rows={[['Runs in range', a.runs.total], ...counts(a.runs.by_state).map(([k, v]) => [`State ${k}`, v]), ...counts(a.runs.by_type).map(([k, v]) => [`Type ${k}`, v])]} />
      </Section>
      <Section id="report-lead-time" title="Lead time">
        <p>Created to finished, finished runs only.</p>
        <p><Spread m={a.lead_time_seconds} /></p>
      </Section>
      <Section id="report-acceptance" title="Acceptance rate">
        <p>
          {isNull(a.acceptance_rate) ? <NotReported reason={a.acceptance_rate.reason} /> : <>{percent(a.acceptance_rate.value)} ({a.acceptance_rate.accepted} accepted of {a.acceptance_rate.decided} decided)</>}
        </p>
      </Section>
      <Section id="report-approval-wait" title="Approval wait">
        {isNull(wait) ? <p><NotReported reason={wait.reason} /></p> : <Table head={['Gate', 'Wait']} rows={Object.entries(wait).map(([g, m]) => [g, <Spread key={g} m={m} />])} />}
      </Section>
      <Section id="report-retries" title="Retries">
        <p>{isNull(a.retries) ? <NotReported reason={a.retries.reason} /> : `${a.retries.total} retried tasks`}</p>
        {isNull(a.tasks) ? null : (
          <Table head={['Role', 'Tasks', 'Median seconds']} rows={Object.entries(a.tasks.by_role).map(([r, v]) => [r, v.count, v.median_seconds === null ? <NotReported key={r} reason="no durations" /> : duration(v.median_seconds)])} />
        )}
      </Section>
      <Section id="report-providers" title="Provider failure rate">
        {providers.length ? (
          <Table
            head={['Provider', 'Failure rate']}
            rows={providers.map(([p, m]) => [p, isNull(m) ? <NotReported key={p} reason={m.reason} /> : `${percent(m.value)} (${m.failures} of ${m.tasks} finished tasks)`])}
          />
        ) : (
          <p>No provider has run a task in this range.</p>
        )}
      </Section>
      <Section id="report-tdd" title="TDD cycles">
        {isNull(a.tdd) ? <p><NotReported reason={a.tdd.reason} /></p> : (
          <Table head={['Measure', 'Value']} rows={[['Cycles', a.tdd.cycles.total], ['Accepted', a.tdd.cycles.accepted], ...Object.entries(a.tdd.cycles.rejected).map(([p, n]) => [`Rejected in ${p}`, n])]} />
        )}
      </Section>
      <Section id="report-verification" title="Verification pass rate">
        {isNull(pass) ? <p><NotReported reason={pass.reason} /></p> : <Table head={['Check', 'Pass rate']} rows={Object.entries(pass).map(([k, v]) => [k, `${percent(v.value)} (${v.passed} of ${v.total})`])} />}
        <p>First attempt: {isNull(first) ? <NotReported reason={first.reason} /> : `${percent(first.value)} (${first.passed_first} of ${first.verified} verified runs passed every check first time)`}</p>
      </Section>
      <Section id="report-rework" title="Rework">
        {isNull(a.rework) ? <p><NotReported reason={a.rework.reason} /></p> : (
          <Table
            head={['Measure', 'Value']}
            rows={[['Runs with a revised specification', a.rework.spec_revisions], ['Runs with revised Gherkin', a.rework.gherkin_revisions], ['Changes requested', a.rework.changes_requested], ['Findings routed', a.rework.findings_routed]]}
          />
        )}
      </Section>
      <Section id="report-cost" title="Cost">
        {isNull(total) ? <p><NotReported reason={total.reason} /></p> : (
          <p>
            Total {money(total.value)} {costLabel(total) ? <strong>{costLabel(total)}</strong> : null}
          </p>
        )}
        {Object.keys(cost.by_role).length ? <Table head={['Role', 'Cost']} rows={Object.entries(cost.by_role).map(([k, v]) => [k, money(v)])} /> : null}
        {Object.keys(cost.by_provider).length ? <Table head={['Provider', 'Cost']} rows={Object.entries(cost.by_provider).map(([k, v]) => [k, money(v)])} /> : null}
        <p className="hint">Only costs reported by tasks are summed; nothing is estimated from tokens.</p>
      </Section>
      <Section id="report-usage" title="Usage">
        {!a.usage || isNull(a.usage.total) ? (
          <p><NotReported reason={a.usage?.total && isNull(a.usage.total) ? a.usage.total.reason : 'no usage reported'} /></p>
        ) : (
          <>
            <p>
              Total tokens: <strong>{(a.usage.total.tokens ?? 0).toLocaleString()}</strong>
              {a.usage.total.input_tokens != null ? ` (${a.usage.total.input_tokens.toLocaleString()} in, ${(a.usage.total.output_tokens ?? 0).toLocaleString()} out)` : ''}
              {a.usage.total.cost != null ? ` · ${money(a.usage.total.cost)}` : ''}
            </p>
            {Object.keys(a.usage.by_model).length ? (
              <>
                <h3>By model</h3>
                <Table
                  head={['Model', 'Tokens', 'Cost', 'Tasks']}
                  rows={Object.entries(a.usage.by_model).map(([m, d]) => [
                    m,
                    d.tokens ? d.tokens.toLocaleString() : '—',
                    d.cost ? money(d.cost) : '—',
                    d.tasks,
                  ])}
                />
              </>
            ) : null}
            {Object.keys(a.usage.by_week).length ? (
              <>
                <h3>By week</h3>
                <Table
                  head={['Week', 'Tokens', 'Cost', 'Tasks']}
                  rows={Object.entries(a.usage.by_week).map(([w, d]) => [
                    w,
                    d.tokens ? d.tokens.toLocaleString() : '—',
                    d.cost ? money(d.cost) : '—',
                    d.tasks,
                  ])}
                />
              </>
            ) : null}
          </>
        )}
      </Section>
    </>
  );
}

export function ReportsScreen() {
  const projects = useResource('reports-projects', (c) => calls.projects(c), {});
  const [project, setProject] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const pid = useId();
  const fromId = useId();
  const toId = useId();
  const available = projects.data?.items.filter((p) => p.status === 'available') ?? [];
  const bad = (from && !validDay(from)) || (to && !validDay(to)) ? 'Use dates written YYYY-MM-DD' : from && to && validDay(from) && validDay(to) && from > to ? 'From must not be after To' : '';
  const ready = !!project && !bad;
  const report = useResource(`report-${project}-${from}-${to}`, (c) => calls.analytics(c, project, from, to), { project }, ready);
  return (
    <section>
      <h1>Reports</h1>
      <p className="hint">Computed from the registry of the project. Nothing is estimated and nothing is sent anywhere.</p>
      <div className="row">
        <label htmlFor={pid}>Project</label>
        <select id={pid} value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">Choose a project</option>
          {available.map((p) => (
            <option key={p.id} value={p.id}>{p.id}</option>
          ))}
        </select>
        <label htmlFor={fromId}>From</label>
        <input id={fromId} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <label htmlFor={toId}>To</label>
        <input id={toId} type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      {bad ? <p className="banner danger" role="alert">{bad}</p> : null}
      {ready ? <Loaded res={report}>{(a) => <Report a={a} />}</Loaded> : bad ? null : <p>Choose a project to see its report.</p>}
    </section>
  );
}
