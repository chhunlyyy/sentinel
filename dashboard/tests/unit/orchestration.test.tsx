import { describe, expect, test, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createClient } from '../../src/api/client.ts';
import { buildPath } from '../../src/api/routes.ts';
import { AppProvider } from '../../src/state/app.tsx';
import { FolderPicker } from '../../src/components/FolderPicker.tsx';
import { useState } from 'react';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('client PUT and DELETE', () => {
  test('a PUT carries the CSRF header and a JSON body, a DELETE carries the header and no body', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith('/session')) return json({ csrf: 'tok', user: { name: 'dev', role: 'admin' } });
      return json({ ok: true });
    });
    const c = createClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await c.put(buildPath('setOrchestrator'), { id: 'claude' });
    await c.del(buildPath('removeRepository', { pid: 'p', rid: 'backend' }));
    const put = calls.find((x) => x.init.method === 'PUT')!;
    expect((put.init.headers as Record<string, string>)['X-Sentinel-CSRF']).toBe('tok');
    expect(put.init.body).toBe('{"id":"claude"}');
    const del = calls.find((x) => x.init.method === 'DELETE')!;
    expect(del.url).toBe('/api/v1/projects/p/repositories/backend');
    expect((del.init.headers as Record<string, string>)['X-Sentinel-CSRF']).toBe('tok');
    expect(del.init.body).toBeUndefined();
  });
});

describe('route paths of the new calls', () => {
  test('encoded ids and queries', () => {
    expect(buildPath('providerTest', { id: 'claude' })).toBe('/api/v1/providers/claude/test');
    expect(buildPath('agents', {}, { project: 'my proj' })).toBe('/api/v1/agents?project=my%20proj');
    expect(buildPath('fsDirs', {}, { path: '/home/dev' })).toBe('/api/v1/fs/dirs?path=%2Fhome%2Fdev');
    expect(buildPath('fsDirs')).toBe('/api/v1/fs/dirs');
  });
});

describe('FolderPicker', () => {
  test('browses folders, goes up and picks one', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('path=%2Fhome%2Fdev%2Fprojects')) return json({ path: '/home/dev/projects', parent: '/home/dev', items: [{ name: 'api', path: '/home/dev/projects/api', is_git: true }] });
      return json({ path: '/home/dev', parent: '/home', items: [{ name: 'projects', path: '/home/dev/projects', is_git: false }] });
    });
    vi.stubGlobal('fetch', fetchMock);
    function Host() {
      const [v, setV] = useState('');
      return (
        <AppProvider stream={false}>
          <FolderPicker label="Project folder" value={v} onChange={setV} allowNew />
        </AppProvider>
      );
    }
    render(<Host />);
    await user.click(screen.getByRole('button', { name: 'Browse folders for Project folder' }));
    await user.click(await screen.findByRole('button', { name: 'Open projects' }));
    expect(await screen.findByText('git')).toBeInTheDocument();
    await user.type(screen.getByLabelText('New folder name'), 'fresh');
    await user.click(screen.getByRole('button', { name: 'Create folder here' }));
    await waitFor(() => expect(screen.getByLabelText('Project folder')).toHaveValue('/home/dev/projects/fresh'));
    vi.unstubAllGlobals();
  });
});
