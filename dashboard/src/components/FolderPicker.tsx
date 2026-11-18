import { useEffect, useId, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { DirsAnswer } from '../api/orchestration.ts';
import { useApp } from '../state/app.tsx';

export interface FolderPickerProps {
  label: string;
  value: string;
  onChange: (path: string) => void;
  /** offer a field for the name of a new folder inside the folder being browsed */
  allowNew?: boolean;
  hint?: string;
  error?: string;
  testId?: string;
}

/** A path field plus a browser over GET fs/dirs. Directories only; the path stays editable by hand. */
export function FolderPicker({ label, value, onChange, allowNew = false, hint, error, testId = 'folder-picker' }: FolderPickerProps) {
  const app = useApp();
  const uid = useId();
  const [open, setOpen] = useState(false);
  const [listing, setListing] = useState<DirsAnswer | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState('');

  const load = async (path?: string) => {
    setLoading(true);
    try {
      setListing(await calls.fsDirs(app.client, path));
      setFailure(null);
    } catch (e) {
      setFailure(e as ApiError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && !listing && !failure) void load(value.startsWith('/') ? value : undefined);
  }, [open]);

  const choose = (path: string) => {
    onChange(path);
    setOpen(false);
  };
  const chooseNew = () => {
    if (!listing || !newName.trim()) return;
    const base = listing.path.endsWith('/') ? listing.path : `${listing.path}/`;
    choose(`${base}${newName.trim()}`);
    setNewName('');
  };

  return (
    <div className="field folder-picker" data-testid={testId}>
      <label htmlFor={`${uid}-path`}>{label}</label>
      <div className="row">
        <input
          id={`${uid}-path`}
          type="text"
          className="grow"
          value={value}
          autoComplete="off"
          placeholder="/absolute/path"
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${uid}-err` : undefined}
        />
        <button type="button" className="secondary" aria-expanded={open} aria-label={`Browse folders for ${label}`} onClick={() => setOpen((o) => !o)}>
          {open ? 'Close browser' : 'Browse'}
        </button>
      </div>
      {hint ? <p className="hint">{hint}</p> : null}
      {error ? (
        <p className="field-error" id={`${uid}-err`}>
          {error}
        </p>
      ) : null}
      {open ? (
        <div className="panel dir-browser" role="group" aria-label={`Folders for ${label}`}>
          {failure ? <p className="field-error">{failure.text}</p> : null}
          {listing ? (
            <>
              <p className="row">
                <strong>Folder</strong> <code data-testid="dir-current">{listing.path}</code>
                {listing.parent ? (
                  <button type="button" className="secondary" onClick={() => void load(listing.parent ?? undefined)}>
                    Up one level
                  </button>
                ) : null}
                <button type="button" onClick={() => choose(listing.path)}>
                  Use this folder
                </button>
              </p>
              {loading ? <p className="hint">Loading</p> : null}
              {listing.items.length === 0 ? <p className="hint">No sub folders</p> : null}
              <ul className="plain dir-list">
                {listing.items.map((d) => (
                  <li key={d.path}>
                    <button type="button" className="secondary dir-item" aria-label={`Open ${d.name}`} onClick={() => void load(d.path)}>
                      {d.name}
                    </button>
                    {d.is_git ? <span className="chip">git</span> : null}
                  </li>
                ))}
              </ul>
              {allowNew ? (
                <div className="row">
                  <label htmlFor={`${uid}-new`}>New folder name</label>
                  <input id={`${uid}-new`} type="text" value={newName} autoComplete="off" onChange={(e) => setNewName(e.target.value)} />
                  <button type="button" className="secondary" disabled={!newName.trim()} onClick={chooseNew}>
                    Create folder here
                  </button>
                </div>
              ) : null}
            </>
          ) : failure ? null : (
            <p className="hint">Loading</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
