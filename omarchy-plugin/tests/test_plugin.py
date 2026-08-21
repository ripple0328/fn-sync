import importlib.util
import ipaddress
import json
import sys
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
        self.assertIn('backText: root.l10n("Back to Settings", "返回设置")', panel)
        self.assertIn('backText: root.l10n("Back to Tasks", "返回任务")', panel)
        self.assertIn("PanelActionButton {", header)
        self.assertIn('iconText: "󰁍"', header)
        self.assertIn("tooltipText: root.backText", header)
        self.assertNotIn('text: root.backText', header)
        self.assertIn("hoverColor: root.accent", header)
        self.assertIn("Accessible.role: Accessible.Button", header)
        self.assertIn("focusable: true", header)

    def test_optional_task_state_is_always_a_boolean(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("if (!task)\n            return false;", panel)
        self.assertIn('String(task.status.error_code || "") === "access-marker"', panel)
        self.assertIn(": false;", panel)

    def test_control_wrapper_prefers_the_user_install(self):
        control = (ROOT / "scripts" / "fn-syncctl").read_text(encoding="utf-8")
        self.assertIn('${FNSYNC_BIN:-$HOME/.local/bin/fn-sync}', control)
        self.assertIn('FNSYNC_LANGUAGE="$language"', control)

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
