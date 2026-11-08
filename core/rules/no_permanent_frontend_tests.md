## Test infrastructure is transient in client repos

Repos whose role is frontend or mobile keep no permanent test suite. Any runner, mutation tool, test file, config, report directory, or test-only dependency or script you add is a transient verification tool: note `git status --porcelain` and the manifest and lockfile state before adding anything, use it, then remove all of it and restore the manifest and lockfile to their pre-run state. Confirm with `git status --porcelain` that only the increment's own source changes remain, and that lint, typecheck, and build still pass.
