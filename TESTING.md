# Testing FN sync

The test suite deliberately separates pure safety rules from package-level behavior.
No test contacts a real NAS, changes the desktop's saved connections, or reads a real
password. The CLI integration suite supplies isolated XDG directories and a deterministic
fake rclone process.

## Coverage map

| Area | Evidence |
| --- | --- |
| Configuration migration and private writes | `tests/test_core.py` |
| URL, local path, remote path, overlap, interval and bandwidth validation | `tests/test_core.py` |
| Reusable NAS authorization and credential fallback | unit tests plus `tests/test_cli_integration.py` |
| Folder navigation and local NAS discovery | `tests/test_core.py`, `tests/test_discovery.py` |
| Two-way preview, conflict winner and first initialization | unit tests, fake-rclone CLI lifecycle, and local real-WebDAV E2E |
| Upload-only and download-only non-destructive copy semantics | unit tests plus local real-WebDAV E2E |
| Access markers, pause-on-mismatch and explicit repair | `tests/test_core.py` |
| Deletion guard, conflict copies, backup directories and task locks | `tests/test_core.py` |
| Background enable/disable, sync-now, status and logs | `tests/test_cli_integration.py` |
| Package contents, Arch/AUR template parity, release archive integrity, version consistency, desktop localization and services | `tests/test_distribution.py`, `scripts/verify-package.sh` |
| Bundled Omarchy plugin installation, backup, service enable and bar enable | `tests/test_installer.py` |
| Plugin manifest, QML parsing, discovery and official Omarchy validation | `omarchy-plugin/tests`, `scripts/ci.sh` |
| README screenshots, CI gates, GitHub Release, gated/manual AUR publish and plugin subtree publish | `tests/test_publishing.py` |

## Local checks

Run the complete dependency-free suite:

```bash
./scripts/ci.sh
```

When `ruff` and `shellcheck` are installed, the same command also runs them. GitHub Actions
installs both tools and always enforces those lint checks. Package verification runs after
`./scripts/build-packages.sh`:

```bash
./scripts/verify-package.sh
```

CI also starts an authenticated rclone WebDAV server entirely inside the runner and proves
two-way initialization, incremental transfer, access-marker stopping and repair, and the
non-deleting behavior of both one-way modes. It records branch coverage for the Python
controller and discovery helper, with a hard
minimum in `pyproject.toml`. A real fnOS smoke test remains a release acceptance check rather
than an automated test because it requires a private NAS account and modifies remote files.
