<p align="right">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

# FN sync

[![CI](https://github.com/ripple0328/fn-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/ripple0328/fn-sync/actions/workflows/ci.yml)
[![Release](https://github.com/ripple0328/fn-sync/actions/workflows/release.yml/badge.svg)](https://github.com/ripple0328/fn-sync/actions/workflows/release.yml)

**FN sync brings safe, native fnOS file synchronization to Linux and Omarchy.**
It uses the documented fnOS WebDAV service, rclone's proven transfer engine,
and an Omarchy-native panel for connections, tasks, status, and recovery. It
does not depend on the private protocol used by the official Windows and macOS
clients.

The application is displayed as **FN sync**, or **飞牛** when the system
interface language is Chinese. The package name, command, and internal paths
remain `fn-sync` for installation and script compatibility.

> The current version is `0.9.1`. Discovery, authorization, folder browsing,
> and large transfers have been validated against a real fnOS NAS. The Omarchy
> panel has only two top-level destinations, **Tasks** and **Settings**.
> Connection pages use quiet, theme-aware breadcrumb navigation, and each task
> card displays its sync state only once. Start with a small, newly created
> folder for the first trial.

## Interface

| Tasks and sync status | Settings and saved NAS connections |
| --- | --- |
| ![FN sync tasks](docs/screenshots/tasks.png) | ![FN sync settings](docs/screenshots/settings.png) |

## Architecture

| Layer | Responsibility | Requires Omarchy |
| --- | --- | --- |
| `fn-sync` controller + rclone | WebDAV transfer, task state, conflict handling, and deletion safeguards | No |
| systemd user service | Scheduled background synchronization | No |
| GTK 4/GJS client | Connections, tasks, first-sync guidance, pause, and sync-now actions | No |
| `community.fnos-sync` plugin | Native Omarchy panel plus a bundled copy of the controller and GTK client | Yes; self-contained |

The Omarchy plugin includes the controller and GTK client so it can be installed
like a regular plugin. File transfers still run in a separate Python/rclone
process, never inside the long-running `omarchy-shell` process, and the plugin
never stores WebDAV passwords.

Plugin status refreshes when the widget loads, whenever the panel opens, after
an action completes, and on a background timer. The default interval is 30
seconds and can be changed with the plugin's `refreshIntervalSec` setting, so
the panel does not need a manual refresh button.

## Features

- NAS connections are separate from sync tasks. Authorize each NAS account
  once, then reuse it across multiple tasks.
- The new-connection screen scans the directly connected private LAN. A
  responding WebDAV endpoint can fill the address automatically; multiple
  devices are presented as choices.
- A new authorization must successfully sign in and list folders before it can
  be saved. Changing any connection field requires another test, and no
  credentials are persisted while testing.
- Native folder pickers select the local directory and browse the NAS rather
  than requiring manually guessed paths.
- Two-way sync, upload-only, and download-only modes.
- A two-step first-sync guide for two-way tasks: choose which side wins only
  same-name conflicts, run the read-only **Check first sync**, then use the
  single **Start first sync** primary action.
- The read-only check reports elapsed time and scanning progress without
  changing files. Its conflict rule is recorded; changing that rule requires a
  new check so preview and initialization cannot disagree.
- Automatic background sync starts after the first sync succeeds. Before that,
  the UI shows guidance instead of a switch that looks broken or disabled.
- Routine conflicts preserve both copies with `.Omarchy-conflictN` and
  `.NAS-conflictN` suffixes.
- Files are backed up to a version directory before deletion. A run aborts if
  more than 50% of a side would be deleted at once.
- Matching `FN_SYNC_ACCESS_TEST` markers are checked before every two-way
  scan. A missing, changed, or inaccessible marker pauses the task before any
  files are scanned or modified.
- **Repair safety check and resume** recreates and verifies only FN sync's
  marker after the user confirms both paths. It never changes unrelated files.
- Task logs rotate at 5 MiB and retain one previous log.
- The filesystem root and an entire home directory are rejected, as are
  overlapping local or NAS roots across tasks.
- HTTPS is the default. Plain HTTP and skipped certificate validation require
  explicit opt-in.
- Passwords prefer the desktop Secret Service. FN sync creates a temporary
  `0600` rclone configuration only while syncing and deletes it afterward.
- If Secret Service is unavailable, credentials fall back to rclone's
  reversible obscured format in a `0600` file. Obscuring is not encryption.
- Common temporary files and FN sync's internal version directories are
  filtered by default.

## Install on Omarchy

Install and enable the Git-managed plugin with the normal Omarchy command:

```bash
omarchy plugin add https://github.com/ripple0328/omarchy-fn-sync.git --enable --yes
```

That is the only FN Sync installation command an Omarchy user needs. The plugin
repository contains the controller, GTK client, and background-service unit.
On first open, a setup card offers to install any missing signed Arch runtime
components through the system authentication dialog. It does not install an
AUR package or ask the user to run a second command. The setup is explicit
because Omarchy's plugin installer deliberately never executes install hooks or
requests elevated privileges.

Update it through Omarchy like any other Git-managed plugin:

```bash
omarchy plugin update community.fnos-sync --yes
```

The `fn-sync` Arch/AUR package remains an optional system-wide distribution for
non-Omarchy desktops and command-line-only installations. It is not a dependency
of the Omarchy plugin. If it is already installed, the Git-managed plugin uses
its own matching bundled runtime so plugin and client updates cannot drift.

To build the pacman package, standalone plugin archive, and portable bundle
from source:

```bash
git clone https://github.com/ripple0328/fn-sync.git
cd fn-sync
./scripts/build-packages.sh
```

Then run the bundle installer as the normal desktop user. It asks for `sudo`
only when invoking pacman:

```bash
./scripts/install-omarchy-bundle.sh
```

Artifacts are written to `dist/`:

- `fn-sync-0.9.1-1-any.pkg.tar.zst`: Arch/pacman system package.
- `fn-sync-omarchy-plugin-0.9.1.tar.gz`: self-contained Omarchy plugin.
- `fn-sync-omarchy-bundle-0.9.1.tar.gz`: portable bundle containing both
  packages and the installer.

After installation, the official double-loop FN Sync mark appears on the right
side of the bar and opens a panel that follows the active Omarchy theme. The
mark's foreground, accent, and error colors update with the theme. The panel
has only **Tasks** and **Settings** as top-level destinations; NAS authorization
lives under Settings and is reused by tasks. Passwords pass through standard
input only while connecting or reauthorizing and are never stored in task data,
QML, or plugin settings.

The name and icon reference the [official FN Connect download
page](https://fnnas.com/download?key=fn-sync) and [official FN Connect
documentation](https://help.fnnas.com/articles/v1/sync/how-to-use). The Omarchy
bar uses the original double-arrow outline as a transparent mask and colors it
from the current theme. FN/飞牛 and its icon remain trademarks of their owner.

The interface follows the desktop locale by default: `zh*` selects Simplified
Chinese and every other locale selects English. Settings can override this
with **System default**, **English**, or **简体中文**. The full client inherits
the same choice when opened from the panel.

Non-Omarchy Linux desktops can use the GTK fallback with `fn-sync ui`.

The release pipeline runs linting, Python/CLI/installer tests, the official
Omarchy manifest validator, and a clean Arch build before creating a GitHub
Release. Once a dedicated AUR SSH key is configured, the same pipeline can push
`PKGBUILD`, `.SRCINFO`, and the install message to AUR. A separate workflow
publishes the plugin subtree to `ripple0328/omarchy-fn-sync`, with
`manifest.json` at the repository root.

### User-level development installation

To install from source without writing to the pacman database:

```bash
omarchy pkg add rclone python gjs gtk4 libsecret libnotify
./scripts/install.sh
./scripts/install-omarchy-plugin.sh
```

## Configure fnOS

1. Enable WebDAV under file-sharing protocols in fnOS.
2. Prefer HTTPS and note the complete WebDAV URL and port shown by fnOS.
3. Create a dedicated subdirectory for the Linux sync.
4. Prefer a dedicated fnOS user with read/write access only to the required
   share instead of an administrator account.
5. Authorize the NAS once under **Settings → NAS connections** in the Omarchy
   panel, or use the GTK fallback, then create one or more tasks.
6. Select the conflict rule, complete **Check first sync**, and choose
   **Start first sync**.

The first-sync check traverses every included directory on both sides.
Generated trees such as `node_modules`, `deps`, `_build`, and Xcode or
Android build output can add substantial time and WebDAV requests. The check
uses `--dry-run`, changes no files, and can be stopped from its progress card.
If a root-folder test succeeds but a large scan intermittently reports
`401 Unauthorized`, fnOS WebDAV may be rejecting bursts of deep requests
rather than rejecting the password. FN sync keeps HTTPS, disables HTTP/2
multiplexing for that connection, reduces rclone checkers/transfers to `2/2`,
and increases retry spacing. Directory modification times are not coordinated,
so the client does not write them back after comparing files.

See the [official fnOS WebDAV
documentation](https://help.fnnas.com/articles/v1/file-service/webdav). Never
post a NAS password in an issue, chat, or log.

### Local network discovery

Opening a new NAS form automatically scans directly connected private IPv4
networks. The scan is bounded to at most one `/24` per local subnet and probes
only fnOS management ports `5667/5666/8001/8000` and common WebDAV ports
`5006/5005`. It performs only TCP, HTTP(S), and WebDAV `OPTIONS` reads; it
does not sign in or modify the NAS.

The official FN Connect client discovers its management/authorization address
(currently HTTPS `5667` by default), while FN sync transfers through WebDAV.
If discovery finds only fnOS management, the form does not guess port `5006`;
it asks the user to enable or inspect WebDAV under **Settings → File sharing
protocols**. An address is filled automatically only after a default WebDAV
port responds, and it still must pass **Test login & folders** before saving.
Custom WebDAV ports, cross-VLAN discovery, VPNs, and FN ID are not scanned.

## CLI

The primary command has been `fn-sync` since version `0.3.0`. The legacy
`fnsync` command remains as a compatibility alias, and existing
`~/.config/fnsync` tasks and credential references are preserved.

```bash
fn-sync --version
fn-sync doctor
fn-sync connection add --name "Home NAS" --url https://nas.example/dav/ --username alice --password-stdin
fn-sync connection list
fn-sync connection test <connection-id>
fn-sync connection folders <connection-id> --json
fn-sync task add --name Docs --connection <connection-id> --local "$HOME/Sync/Docs" --remote-path Sync/Docs
fn-sync task repair-access <task-id> --resume
fn-sync task list
fn-sync status --json
fn-sync task test <task-id>
fn-sync task preview <task-id> --winner local
fn-sync task initialize <task-id> --winner local --apply
fn-sync task run <task-id> --dry-run
fn-sync sync-now
fn-sync logs <task-id>
```

## Compared with the official clients

| Capability | Official Windows/macOS client | FN sync |
| --- | --- | --- |
| IP/domain connection | Supported | WebDAV URL |
| Local NAS discovery | Supported | Supported; fills only a responding WebDAV address and requires a test |
| One authorization reused by multiple tasks | Supported | Supported; connections and tasks are separate |
| FN ID/remote relay | Supported | Not supported; requires direct fnOS WebDAV access |
| Two-way, upload-only, download-only | Supported | Supported |
| First-task experience | Starts immediately | Runs one read-only safety check before starting |
| On-demand placeholders | Windows only | Not supported |
| Conflict handling | Keeps a local conflict copy | Keeps conflict copies on both sides |
| Tray and management UI | Official tray | Native Omarchy plugin; GTK fallback |
| Linux desktop | No official client | GTK client + systemd service |

The same NAS directory can continue to be used by the official macOS or Windows
client while Linux accesses it over WebDAV. Do not let two sync programs watch
the same local Linux directory at the same time.

## Validation

- 91 automated tests cover real WebDAV two-way/one-way transfers, complete CLI
  connection and task lifecycles, streamed progress and silent timeouts,
  background scheduling, Secret Service, LAN discovery, the one-step installer
  sandbox, packaged-controller startup, release-source integrity,
  package/publishing contracts, bilingual documentation, and standalone plugin
  tests. Combined Python line-and-branch coverage is gated at 85%; the current
  suite measures 87%.
- The Omarchy 4.0 plugin manifest and QML syntax pass validation.
- The pacman package, standalone plugin archive, and portable bundle pass
  structural verification.
- GTK/GJS modules pass syntax and import checks without a display server.
- A real transfer suite backed by `rclone serve webdav` exercises initial
  two-way merge, incremental two-way sync, conflict copies, versioned deletion
  backup, access-marker aborts, upload-only source-deletion isolation, and
  download-only source-deletion isolation.

## Known limitations

- WebDAV cannot reliably preserve modification times, so the first merge does
  not offer an automatic “newer file wins” option.
- Synchronization uses periodic scans rather than kernel events plus fnOS push.
- Windows-style placeholders, FN ID relay, cross-subnet discovery, and the
  official client's token/2FA flow are not supported.
- The public fnOS API is not an external desktop-sync protocol. See the
  [research notes](docs/research.md).

## Test locally

```bash
./scripts/ci.sh
./scripts/build-packages.sh
./scripts/verify-package.sh
```

Coverage details and the remaining real-NAS validation boundary are documented
in [TESTING.md](TESTING.md).
