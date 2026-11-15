import type { WCostTotal } from './api/wire.ts';

export function isNull(m: unknown): m is { value: null; reason: string } {
  return !!m && typeof m === 'object' && (m as { value?: unknown }).value === null && typeof (m as { reason?: unknown }).reason === 'string';
}

export function duration(seconds: number): string {
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const min = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return min ? `${h} h ${min} min` : `${h} h`;
  if (min) return sec ? `${min} min ${sec} s` : `${min} min`;
  return `${sec} s`;
}

export function percent(v: number): string {
  const p = Math.round(v * 1000) / 10;
  return `${p}%`;
}

export function costLabel(c: WCostTotal): string {
  return c.partial ? `partial: ${c.unreported_tasks} ${c.unreported_tasks === 1 ? 'task' : 'tasks'} did not report cost` : '';
}

export function money(v: number): string {
  return v.toFixed(2).replace(/\.00$/, '');
}
