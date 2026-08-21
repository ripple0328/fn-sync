# fn-sync 0.4.0 design QA

final result: passed

## Comparison target

- Source visual truth: `/tmp/fn-official-ui.SI7Bei/01-connect.png` and `/tmp/fn-official-ui.SI7Bei/06-settings.png`, downloaded from the current official fnOS help article.
- Rendered implementation: `/tmp/screenshot-2026-08-17_10-58-54.png` and `/tmp/screenshot-2026-08-17_10-59-03.png`, captured from the installed Omarchy plugin.
- Combined comparison evidence: `/tmp/fn-sync-design-qa/comparison.png`.
- State: empty client, connect/authorize NAS form, and settings screen.
- Full desktop viewport: 3840 x 2160 physical pixels at the active Omarchy display scale.
- Normalized source crops: 900 x 640 pixels.
- Normalized implementation crops: 717 x 640 and 796 x 640 pixels. The width difference is intentional because the target is an Omarchy right-side panel rather than the official full desktop window.

## Findings

- No actionable P0, P1, or P2 visual mismatch remains.
- Information architecture: the implementation preserves the official connection-first model and the separate Tasks, NAS, and Settings surfaces. It intentionally combines direct WebDAV connection and password entry in one compact form because the public WebDAV route cannot reproduce the official token-authorization window.
- Fonts and typography: the hierarchy, weights, line wrapping, labels, and field grouping are clear. The active Omarchy theme font intentionally replaces the official client's light sans-serif typography so the plugin remains native to the desktop.
- Spacing and layout rhythm: the narrow panel uses consistent Omarchy spacing, radii, borders, field heights, and vertical rhythm. Persistent controls remain visible without overflow in the captured states.
- Colors and visual tokens: foreground, accent, muted, surface, border, and error colors come from live Omarchy tokens. The dark rose palette is therefore an intentional theme adaptation of the official light-blue UI.
- Image quality and asset fidelity: the header and bar use the official fn Sync double-arrow raster mask with live theme tinting. No approximate hand-drawn logo, emoji, or placeholder asset is used.
- Copy and content: connection reuse, secure credential handling, HTTPS guidance, and the private-API parity boundary are explicit. Task-specific paths and sync rules are no longer mixed with NAS authorization.

## Interaction and runtime evidence

- Opened the installed Tasks view through the plugin IPC target.
- Opened the NAS view and empty state.
- Opened the Connect NAS form.
- Opened the Settings view.
- Verified the installed 0.4.0 manifest, package contents, active user service, and plugin discovery.
- Checked the current user journal; no `community.fnos-sync`, `Panel.qml`, `BarWidget.qml`, or `FnSyncIcon.qml` runtime error was emitted after the shell restart.

## Comparison history

- Initial installed capture briefly showed the previous component instance after a hot reload. Restarting `omarchy-shell` loaded the new 0.4.0 panel. The post-fix captures listed above show the new Tasks, NAS, Connect NAS, and Settings states.
- The first comparison crop used logical rather than physical display coordinates. It was regenerated from the 3840 x 2160 captures using the correct physical crop; this was an evidence-preparation issue, not a product defect.

## Follow-up polish

- P3: add editable global bandwidth and log-retention controls if the engine later gains true global settings. The current Settings page accurately presents the implemented security and compatibility behavior instead of showing non-functional controls.
