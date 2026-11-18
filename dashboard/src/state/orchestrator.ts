// A tiny signal so the header refreshes when the orchestrator is changed on the Providers page.
const listeners = new Set<() => void>();

export function onOrchestratorChanged(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function notifyOrchestratorChanged(): void {
  for (const l of Array.from(listeners)) l();
}
