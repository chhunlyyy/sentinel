/** "2026-11-14T09:30:00Z" becomes "2026-11-14 09:30:00 UTC"; always UTC so the screen does not depend on the machine. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 19)} UTC`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(11, 19);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

export function prefix(sha: string | null | undefined, n = 8): string {
  return sha ? sha.slice(0, n) : '';
}
