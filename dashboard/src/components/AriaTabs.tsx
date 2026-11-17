import { useRef, type KeyboardEvent, type ReactNode } from 'react';

export interface TabDef {
  id: string;
  label: string;
}

/** WAI-ARIA tabs with automatic activation: one tab stop, arrow keys, Home and End move between tabs. */
export function AriaTabs({ label, tabs, current, onChange, idPrefix, children }: { label: string; tabs: TabDef[]; current: string; onChange: (id: string) => void; idPrefix: string; children: ReactNode }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let to = -1;
    if (e.key === 'ArrowRight') to = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') to = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = tabs.length - 1;
    if (to < 0) return;
    e.preventDefault();
    onChange(tabs[to].id);
    refs.current[tabs[to].id]?.focus();
  };
  return (
    <>
      <div role="tablist" aria-label={label} className="tabs">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${t.id}`}
            aria-selected={current === t.id}
            aria-controls={`${idPrefix}-panel-${t.id}`}
            tabIndex={current === t.id ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => move(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* the panel is focusable so a keyboard user can reach its content when it holds no control */}
      <div role="tabpanel" tabIndex={0} id={`${idPrefix}-panel-${current}`} aria-labelledby={`${idPrefix}-tab-${current}`}>
        {children}
      </div>
    </>
  );
}
