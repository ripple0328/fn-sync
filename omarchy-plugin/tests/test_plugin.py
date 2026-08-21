import importlib.util
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_PATH = ROOT / "scripts" / "fn_sync_discover.py"
SPEC = importlib.util.spec_from_file_location(
    "fn_sync_plugin_discovery_under_test", DISCOVERY_PATH
)
assert SPEC and SPEC.loader
discovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = discovery
SPEC.loader.exec_module(discovery)


class PluginContractTests(unittest.TestCase):
    def test_manifest_entry_point_and_default_placement(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "community.fnos-sync")
        self.assertEqual(manifest["kinds"], ["bar-widget"])
        self.assertEqual(manifest["barWidget"]["defaultSection"], "right")
        self.assertTrue((ROOT / manifest["entryPoints"]["barWidget"]).is_file())

    def test_panel_keeps_two_top_level_pages_and_localized_brand(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        bar = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "FN sync")
        self.assertEqual(manifest["barWidget"]["displayName"], "FN sync")
        self.assertIn('title: root.l10n("FN sync", "飞牛")', panel)
        self.assertIn('root.showPrimary("tasks")', panel)
        self.assertIn('root.showPrimary("settings")', panel)
        self.assertNotIn('title: "fn-sync"', panel)
        self.assertIn('settings && settings.language || "system"', bar)
        self.assertIn('Quickshell.env("LC_ALL")', bar)
        self.assertIn('/^zh([_.-]|$)/i.test(systemLocale) ? "zh" : "en"', bar)

    def test_subpages_use_contextual_theme_native_navigation(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        header = (ROOT / "PanelPageHeader.qml").read_text(encoding="utf-8")
        self.assertNotIn('text: root.l10n("Back", "返回")', panel)
        self.assertEqual(panel.count("PanelPageHeader {"), 5)
        self.assertIn('parentTitle: root.l10n("Settings", "设置")', panel)
        self.assertIn('parentTitle: root.l10n("Tasks", "任务")', panel)
        self.assertIn('backAccessibleText: root.l10n("Back to Settings", "返回设置")', panel)
        self.assertIn('backAccessibleText: root.l10n("Back to Tasks", "返回任务")', panel)
        self.assertIn("BorderSurface {", header)
        self.assertIn('text: "←"', header)
        self.assertNotIn("PanelActionButton {", header)
        self.assertIn("activeFocusOnTab: true", header)
        self.assertIn("Keys.onReturnPressed: root.backRequested()", header)
        self.assertIn("Keys.onEnterPressed: root.backRequested()", header)
        self.assertIn("Keys.onSpacePressed: root.backRequested()", header)
        self.assertIn("Style.hoverFillFor(root.accent, root.accent)", header)
        self.assertIn("Accessible.role: Accessible.Button", header)
        self.assertIn("Accessible.name: root.backAccessibleText", header)

    def test_optional_task_state_is_always_a_boolean(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("if (!task)\n            return false;", panel)
        self.assertIn('String(task.status.error_code || "") === "access-marker"', panel)
        self.assertIn(": false;", panel)

    def test_control_wrapper_prefers_the_bundled_runtime(self):
        control = (ROOT / "scripts" / "fn-syncctl").read_text(encoding="utf-8")
        self.assertIn('bundled_client="$plugin_dir/runtime/fnsync.py"', control)
        self.assertLess(
            control.index('[ -f "$bundled_client" ]'),
            control.index('[ -x "$HOME/.local/bin/fn-sync" ]'),
        )
        self.assertIn('install-dependencies)', control)
        self.assertIn('pkexec pacman -S --needed --noconfirm python rclone gjs gtk4 libsecret libnotify', control)
        self.assertIn('systemctl --user enable --now fnsync.service', control)
        status_case = control.split('status)', 1)[1].split('bootstrap)', 1)[0]
        self.assertIn('ensure_service', status_case)
        self.assertIn('FNSYNC_LANGUAGE="$language"', control)

    def test_standalone_plugin_contains_the_client_runtime(self):
        for relative in (
            "runtime/fnsync.py",
            "runtime/ui/app.js",
            "runtime/fnsync.service",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        source_controller = ROOT.parent / "src" / "fnsync.py"
        source_ui = ROOT.parent / "ui" / "app.js"
        if source_controller.is_file() and source_ui.is_file():
            self.assertEqual(
                (ROOT / "runtime" / "fnsync.py").read_bytes(),
                source_controller.read_bytes(),
            )
            self.assertEqual(
                (ROOT / "runtime" / "ui" / "app.js").read_bytes(),
                source_ui.read_bytes(),
            )
            return

        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "fnsync.py"), "--version"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"fn-sync {manifest['version']}")
        self.assertGreater((ROOT / "runtime" / "ui" / "app.js").stat().st_size, 1024)

    def test_clean_system_reports_integrated_setup_instead_of_missing_client(self):
        with tempfile.TemporaryDirectory(prefix="fn-sync-plugin-path-") as temp:
            fake_bin = Path(temp) / "bin"
            fake_bin.mkdir()
            os.symlink("/usr/bin/dirname", fake_bin / "dirname")
            env = os.environ.copy()
            env.update({"HOME": str(Path(temp) / "home"), "PATH": str(fake_bin)})
            result = subprocess.run(
                [str(ROOT / "scripts" / "fn-syncctl"), "status", "en"],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["installed"])
            self.assertFalse(payload["ready"])
            self.assertEqual(payload["distribution"], "plugin")
            self.assertEqual(
                payload["missing_dependencies"], "python,rclone,gjs,gtk4"
            )

    def test_large_private_route_is_bounded_to_source_subnet(self):
        routes = [{"dst": "10.0.0.0/8", "prefsrc": "10.23.45.67"}]
        with mock.patch.object(discovery, "_run_ip_json", return_value=routes):
            self.assertEqual(
                discovery.local_private_networks(),
                [ipaddress.ip_network("10.23.45.0/24")],
            )

    def test_management_host_does_not_claim_closed_webdav_port(self):
        result = discovery.ProbeResult(
            status=200,
            headers=(("Server", "fnOS"),),
            body=b"<title>fnOS</title>",
        )
        with mock.patch.object(discovery, "_request", return_value=result):
            device = discovery.inspect_host("192.168.1.20", {5667})
        self.assertIsNotNone(device)
        self.assertEqual(device["management_url"], "https://192.168.1.20:5667/")
        self.assertEqual(device["url"], "")
        self.assertFalse(device["webdav_verified"])

    def test_unrelated_web_server_is_not_reported_as_nas(self):
        result = discovery.ProbeResult(status=200, headers=(("Server", "nginx"),))
        with mock.patch.object(discovery, "_request", return_value=result):
            self.assertIsNone(discovery.inspect_host("192.168.1.30", {5006}))

    def test_webdav_response_is_reported_without_management_port(self):
        result = discovery.ProbeResult(status=401, headers=(("DAV", "1, 2"),))
        with mock.patch.object(discovery, "_request", return_value=result):
            device = discovery.inspect_host("192.168.1.40", {5006})
        self.assertIsNotNone(device)
        self.assertTrue(device["webdav_verified"])
        self.assertEqual(device["url"], "https://192.168.1.40:5006/")


if __name__ == "__main__":
    unittest.main()
