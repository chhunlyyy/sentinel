import type * as T from '../src/api/types.ts';

export interface RunData {
  detail: T.Run;
  next: T.NextStep;
  specification: {
    current: T.SpecificationAnswer;
    versions: T.VersionRow[];
    oldVersions: Record<string, T.SpecificationAnswer>;
  };
  gherkin: T.GherkinAnswer;
  workflow: T.Workflow;
  tdd: T.TddAnswer;
  verification: T.VerificationAnswer;
  trace: T.TraceAnswer;
  changes: T.ChangesAnswer;
  diffs: Record<string, { binary: boolean; truncated: boolean; hunks: T.DiffAnswer['hunks'] }>;
  artifacts: Record<string, { content: string; sha256: string }>;
  logs: Record<string, { lines: string[]; running: boolean }>;
  report: T.ReportAnswer | null;
}

export interface ProjectData {
  readiness: { default: T.Readiness; byWorkflow?: Record<string, T.Readiness> };
  repositories: T.Page<T.Repository>;
  configuration: T.Configuration;
  history: T.Page<T.ConfigVersion>;
  diffs: Record<string, string>;
  audit: T.AuditRow[];
  runs: T.RunSummary[];
}

export interface Db {
  installation: T.Installation;
  runtime: T.Runtime;
  health: T.Health;
  projects: T.Project[];
  projectData: Record<string, ProjectData>;
  /** keyed "<project>/<slug>" */
  runs: Record<string, RunData>;
}
