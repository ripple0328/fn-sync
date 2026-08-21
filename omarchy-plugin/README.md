# FN sync for Omarchy

FN sync is a theme-native Omarchy bar widget and management panel for syncing
Linux folders with an fnOS NAS. It displays as **FN sync**, or **飞牛** when the
system interface language is Chinese.

![FN sync task panel](preview.png)

The panel separates reusable NAS authorization from sync-task setup, matching
the official client's connection-first model. Use the NAS tab once, then reuse
that connection from any number of tasks.

New NAS authorizations are tested before Save is enabled. Sync tasks use native
local-folder selection and a browsable NAS folder picker instead of typed paths.
Opening a new NAS form also starts a bounded scan of the directly connected
private LAN. A responding WebDAV endpoint fills the address automatically;
an fnOS host without WebDAV is labeled clearly and can open the management UI.
The form still requires a successful login and folder test.

This plugin deliberately contains no WebDAV implementation and no stored
credentials. The `fn-sync` AUR package supplies the controller, GTK client,
background service and a bundled copy of this panel.

## Installation

Install the AUR package and its bundled plugin in one command:

```bash
omarchy pkg aur add fn-sync && fn-sync-omarchy-setup
```

Alternatively, keep the plugin as a git-managed Omarchy checkout:

```bash
omarchy pkg aur add fn-sync && omarchy plugin add https://github.com/ripple0328/omarchy-fn-sync.git --enable --yes
```

Use only one method. Update a bundled installation with
`fn-sync-omarchy-setup --update`; update a git-managed installation with:

```bash
omarchy plugin update community.fnos-sync --yes
```

## Removal

Remove the Omarchy panel first. If the system client is no longer needed,
stop its user service before removing the package:

```bash
omarchy plugin remove community.fnos-sync --yes
systemctl --user disable --now fnsync.service
omarchy pkg drop fn-sync
```

Removing the plugin or package does not delete either synchronized folder.
The user's task configuration and logs remain under the normal XDG config and
state directories unless the user removes them separately.

The plugin uses Omarchy's `Color`, `Style`, `BorderSurface`, `KeyboardPanel`,
`Button`, `TextField`, `Dropdown`, and `Toggle` components so it follows the
active theme automatically.

## Guided first sync

The official desktop client starts syncing as soon as a task is created. This
Linux client adds one read-only safety check because WebDAV cannot reliably
identify the newer copy during rclone's first two-way merge. The panel presents
that difference as a short guided flow instead of exposing rclone's preview and
initialization terminology.

Choose whether the computer or NAS copy should be kept only when the same file
differs, run **Check first sync**, then use the single **Start first sync**
button. Files found on only one side are merged regardless of that choice. The
check records its conflict rule, so changing the choice requires a new check.
It streams progress and can be stopped without changing files. A successful
first sync enables automatic background sync; only then is the real pause/on
toggle shown. Raw rclone output remains available as **View technical log** for
troubleshooting, but is not a required review step.

## Safety pause and repair

Every initialized two-way task has a small `FN_SYNC_ACCESS_TEST` marker on both
sides. fn-sync verifies the exact marker before the expensive file scan. If it
is missing or changed, the task pauses immediately and no files are modified.
After confirming that the displayed local and NAS folders are correct, use
**Repair safety check and resume**. That action recreates only fn-sync's marker,
verifies both copies, and then resumes automatic sync. The client never repairs
the marker silently because doing so could hide an accidentally changed remote
folder. Task logs rotate at 5 MiB and retain one previous file.

## Automatic status refresh

Status is refreshed when the widget loads, whenever the panel opens, after an
action finishes, and periodically in the background. The default interval is
30 seconds and can be changed with the plugin's `refreshIntervalSec` setting.
There is no manual refresh button in the panel.

## Security and Linux scope

Passwords are requested only while connecting or reauthorizing a NAS. The
client prefers the desktop Secret Service and falls back to rclone's reversible
obscured credential format when Secret Service is unavailable. The plugin does
not retain a password.

fn-sync uses fnOS's documented WebDAV service. It supports multiple tasks,
three sync modes, scheduling, filters, previews, conflict copies, deletion
guards, and bounded same-subnet discovery on documented/default fnOS ports.
FN ID relay, cross-subnet discovery, official token/2FA authorization, and
on-demand placeholders depend on private official-client APIs and are not
emulated.

## Development

```bash
python3 -m unittest discover -s tests -v
omarchy plugin validate .
```

The standalone repository runs these checks, ShellCheck and QML parsing on
every push. Releases of the main FN sync repository automatically publish this
plugin subtree to the standalone repository.

## License

MIT. The 飞牛/FN logo remains a trademark of its owner and is used only to
identify compatibility with the fnOS service.
