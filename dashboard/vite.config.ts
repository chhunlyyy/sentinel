import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

function walk(dir: string): string[] {
  return readdirSync(dir)
    .sort()
    .flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
}

function sha(buf: Buffer | string) {
  return createHash('sha256').update(buf).digest('hex');
}

/** Hash of everything the build depends on: src, index.html, package-lock.json and the build config. */
function sourceHash(root: string): string {
  const h = createHash('sha256');
  const files = [...walk(join(root, 'src')), join(root, 'index.html'), join(root, 'package-lock.json'), join(root, 'vite.config.ts'), join(root, 'tsconfig.json')];
  for (const f of files) {
    h.update(relative(root, f).split('\\').join('/'));
    h.update('\0');
    h.update(readFileSync(f));
    h.update('\0');
  }
  return h.digest('hex');
}

const REACT_DOC_LINK = 'https://react.dev/errors/';

/**
 * - AC-DSH-06f: React's production build carries one documentation link inside its minified error text. It is a
 *   message for developers, never fetched, but the bundle must name no remote host. The prefix is cut to a relative
 *   hint. The step fails the build when the link is not found or when any other remote URL remains, so a React
 *   upgrade that changes this cannot slip through unnoticed.
 * - writes manifest.json: sha256 of every file and the source hash (the wheel build compares it in release mode)
 */
function sentinelBuild(root: string): Plugin {
  let outDir = '';
  return {
    name: 'sentinel-build',
    apply: 'build',
    configResolved(config) {
      outDir = join(config.root, config.build.outDir);
    },
    renderChunk(code) {
      return { code: code.replaceAll(REACT_DOC_LINK, 'errors/'), map: null };
    },
    generateBundle(_options, bundle) {
      for (const [name, file] of Object.entries(bundle)) {
        const text = file.type === 'chunk' ? file.code : typeof file.source === 'string' ? file.source : '';
        const remote = /(?:https?:)?\/\/[A-Za-z0-9.-]+\.[a-z]{2,}/.exec(text.replace(/http:\/\/www\.w3\.org\/[A-Za-z0-9/.-]+/g, ''));
        if (remote) this.error(`${name} names a remote resource: ${remote[0]}`);
      }
    },
    closeBundle() {
      const files: Record<string, string> = {};
      for (const f of walk(outDir)) {
        const rel = relative(outDir, f).split('\\').join('/');
        if (rel === 'manifest.json') continue;
        files[rel] = sha(readFileSync(f));
      }
      mkdirSync(outDir, { recursive: true });
      writeFileSync(join(outDir, 'manifest.json'), `${JSON.stringify({ source_sha256: sourceHash(root), files }, null, 2)}\n`);
    },
  };
}

const root = new URL('.', import.meta.url).pathname;

export default defineConfig({
  root,
  base: './',
  plugins: [react(), sentinelBuild(root)],
  build: {
    // The server serves sentinel/dashboard_dist/. It is git-ignored and built by the release step; the wheel
    // includes it through pyproject.toml (artifacts), so Node is never a runtime dependency.
    outDir: process.env.DASHBOARD_OUT_DIR ?? '../sentinel/dashboard_dist',
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 600,
  },
});
