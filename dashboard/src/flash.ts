// One message handed from one screen to the next (for example after a task was created).
let pending: string | null = null;

export function setFlash(text: string) {
  pending = text;
}

export function takeFlash(): string | null {
  const t = pending;
  pending = null;
  return t;
}
