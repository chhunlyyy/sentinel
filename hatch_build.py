"""Hatch build hook: in release mode (SENTINEL_RELEASE=1) the wheel is built only from a fresh dashboard build.

The dashboard build writes sentinel/dashboard_dist/manifest.json with the hash of everything it was built from
(dashboard/src, index.html, package.json, package-lock.json, and the vite, vitest, eslint and tsconfig files). This hook recomputes that hash and
stops the build, naming `npm run build`, when the assets are missing or stale. Without the variable it builds
whatever is there (a wheel with no dashboard_dist serves the placeholder page).
"""
import hashlib
import json
import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


SOURCE_FILES = ("index.html", "package.json", "package-lock.json", "vite.config.ts", "vitest.config.ts", "eslint.config.js", "tsconfig.json")


def _walk(d):
    out = []
    for name in sorted(os.listdir(d)):
        p = Path(d) / name
        out.extend(_walk(p) if p.is_dir() else [p])
    return out


def source_hash(dashboard):
    """The same hash as sourceHash() in dashboard/vite.config.ts."""
    dashboard = Path(dashboard)
    files = _walk(dashboard / "src") + [dashboard / n for n in SOURCE_FILES]
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(dashboard).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if os.environ.get("SENTINEL_RELEASE") != "1":
            return
        root = Path(self.root)
        dist = root / "sentinel" / "dashboard_dist"
        manifest = dist / "manifest.json"
        fix = "run `npm run build` in dashboard/ first"
        if not (dist / "index.html").exists() or not manifest.exists():
            raise RuntimeError(f"release build: sentinel/dashboard_dist is missing; {fix}")
        data = json.loads(manifest.read_text())
        for rel, want in data.get("files", {}).items():
            f = dist / rel
            if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != want:
                raise RuntimeError(f"release build: sentinel/dashboard_dist/{rel} does not match its manifest; {fix}")
        if (root / "dashboard" / "src").is_dir() and data.get("source_sha256") != source_hash(root / "dashboard"):
            raise RuntimeError(f"release build: the dashboard assets are stale (the source hash in manifest.json differs); {fix}")
