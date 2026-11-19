// View models for providers, orchestrator, agent routing, folder browsing and project creation.

export interface Provider {
  id: string;
  label: string;
  command: string;
  installed: boolean;
  path: string | null;
  capabilities: { model_select: boolean; resume: boolean; json_output: boolean };
  models?: { id: string; label: string }[];
}

export interface ProvidersAnswer {
  items: Provider[];
  orchestrator: string | null;
}

export interface OrchestratorAnswer {
  id: string | null;
  installed_ids: string[];
}

export interface ProbeResult {
  id: string;
  ok: boolean;
  message: string;
}

export interface AgentItem {
  role: string;
  runner: string | null;
  model: string | null;
  source: 'default' | 'global' | 'project';
}

export interface ProviderPolicy {
  default: string | null;
  fallback: string[];
  disabled: string[];
}

export interface AgentsAnswer {
  project: string | null;
  roles: string[];
  items: AgentItem[];
  providers: ProviderPolicy;
  single_model: boolean;
  sha256: string | null;
}

export interface SaveAgentsBody {
  project?: string;
  scope: 'project' | 'global';
  sha256?: string;
  agents: Record<string, { runner?: string; model?: string }>;
  providers: { default?: string; fallback?: string[]; disabled?: string[] };
  single_model?: boolean;
}

export interface DirItem {
  name: string;
  path: string;
  is_git: boolean;
}

export interface DirsAnswer {
  path: string;
  parent: string | null;
  items: DirItem[];
}

export interface ProfileItem {
  id: string;
  label?: string;
  detect: string[];
}

export interface NewRepo {
  id?: string;
  path: string;
  role: string;
  profile?: string;
}

export interface CreateProjectBody {
  name: string;
  path: string;
  shared: { mode: 'local' | 'git'; url?: string };
  repos: NewRepo[];
}

export const REPO_ROLES = ['backend', 'frontend', 'mobile', 'app'];
