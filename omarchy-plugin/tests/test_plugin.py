import hashlib
import importlib.util
import ipaddress
import json
import os
import shutil
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

    def test_controller_and_nas_text_is_always_rendered_as_plain_text(self):
        plain_text = (ROOT / "PlainText.qml").read_text(encoding="utf-8")
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        header = (ROOT / "PanelPageHeader.qml").read_text(encoding="utf-8")
        action = (ROOT / "PlainTextAction.qml").read_text(encoding="utf-8")
        dropdown = (ROOT / "PlainTextDropdown.qml").read_text(encoding="utf-8")

        self.assertIn("textFormat: Text.PlainText", plain_text)
        self.assertNotRegex(panel, r"(?m)^\s*Text\s*\{")
        self.assertNotRegex(header, r"(?m)^\s*Text\s*\{")
        self.assertIn("PlainTextAction {", panel)
        self.assertIn("PlainTextDropdown {", panel)
        self.assertNotRegex(action, r"(?m)^\s*Text\s*\{")
        self.assertNotRegex(dropdown, r"(?m)^\s*Text\s*\{")

    def test_connection_form_tests_and_saves_without_retaining_a_password_fingerprint(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        controller = (ROOT / "controller" / "fnsync.py").read_text(encoding="utf-8")
        self.assertIn('root.l10n("Test and save", "测试并保存")', panel)
        self.assertIn("verify_connection_update(", controller)
        self.assertNotIn("verifiedConnectionFingerprint", panel)
        self.assertNotIn("connectionFingerprint", panel)
        self.assertNotIn("pendingVerifyFingerprint", panel)

    def test_controller_caps_external_output_and_persistent_collections(self):
        controller = (ROOT / "controller" / "fnsync.py").read_text(encoding="utf-8")
        for required in (
            "MAX_CAPTURE_BYTES = 512 * 1024",
            "MAX_FOLDER_JSON_BYTES = 1024 * 1024",
            "MAX_STREAM_FORWARD_BYTES = 512 * 1024",
            "MAX_CONNECTIONS = 64",
            "MAX_TASKS = 256",
            "MAX_FOLDER_ITEMS = 1000",
            "def run_bounded_process(",
            "queue.Queue(maxsize=32)",
            "strict_output=False",
            "planned_changes=dry_run_counter.finish()",
        ):
            self.assertIn(required, controller)
        self.assertNotIn("capture_output=True", controller)
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        bar = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        self.assertNotIn("StdioCollector", panel + bar)
        self.assertIn("maxJsonCaptureChars", panel)
        self.assertIn("maxStatusCaptureChars", bar)
        self.assertIn("appendCapture", panel)
        self.assertIn("appendCapture", bar)

    def test_published_controller_source_and_provenance_are_auditable(self):
        controller = ROOT / "controller" / "fnsync.py"
        entrypoint = ROOT / "controller" / "entrypoint.py"
        build_script = ROOT / "controller" / "build-runtime.sh"
        build_requirements = ROOT / "controller" / "requirements-build.txt"
        self.assertTrue(controller.is_file())
        self.assertTrue(entrypoint.is_file())
        self.assertTrue(build_script.is_file())
        self.assertEqual(build_requirements.read_text(encoding="utf-8").strip(), "pyinstaller==6.22.0")
        self.assertIn('--paths "$plugin_dir/controller"', build_script.read_text(encoding="utf-8"))

        parent_controller = ROOT.parent / "src" / "fnsync.py"
        parent_entrypoint = ROOT.parent / "scripts" / "fn-sync-plugin-runtime.py"
        if parent_controller.is_file():
            self.assertEqual(controller.read_bytes(), parent_controller.read_bytes())
            self.assertEqual(entrypoint.read_bytes(), parent_entrypoint.read_bytes())
            return

        source_checkout_runtime = ROOT / "runtime" / "fnsync.py"
        published_binaries = tuple((ROOT / "runtime" / "bin").glob("fn-sync-runtime-*"))
        if source_checkout_runtime.is_file() and not published_binaries:
            self.assertEqual(controller.read_bytes(), source_checkout_runtime.read_bytes())
            return

        provenance_path = ROOT / "BUILD-PROVENANCE.json"
        self.assertTrue(provenance_path.is_file())
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        self.assertRegex(provenance["source_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(provenance["attestation_repository"], "ripple0328/fn-sync")
        for item in provenance["sources"] + provenance["artifacts"]:
            path = ROOT / item["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

        checksums = (ROOT / "runtime" / "SHA256SUMS").read_text(encoding="utf-8")
        for artifact in provenance["artifacts"]:
            self.assertIn(artifact["sha256"], checksums)
            self.assertIn(artifact["path"], checksums)

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
        self.assertIn('bundled_binary="$plugin_dir/runtime/bin/fn-sync-runtime-$runtime_arch"', control)
        self.assertLess(
            control.index('[ -x "$bundled_binary" ]'),
            control.index('[ -f "$bundled_client" ]'),
        )
        self.assertLess(
            control.index('[ -f "$bundled_client" ]'),
            control.index('[ -x "$HOME/.local/bin/fn-sync" ]'),
        )
        self.assertIn('install-dependencies)', control)
        self.assertNotIn('command -v pkexec', control)
        self.assertNotIn('pkexec pacman', control)
        self.assertIn(
            'install the published standalone plugin instead', control
        )
        self.assertIn('managed_runtime_dir="${XDG_DATA_HOME:-$HOME/.local/share}/fn-sync/runtime"', control)
        self.assertIn("rclone_release=\"1.75.0\"", control)
        self.assertIn("https://downloads.rclone.org/v${rclone_release}/${archive}", control)
        self.assertIn("failed its pinned SHA-256 check", control)
        self.assertNotIn("command -v gjs", control)
        self.assertNotIn("command -v gtk4-launch", control)
        self.assertIn('if [ "$client_mode" = python ]; then', control)
        self.assertNotIn("jq -cn", control)
        self.assertIn('exec_client plugin-status --distribution "$client_distribution"', control)
        self.assertIn('service_unit_name="community.fnos-sync.service"', control)
        self.assertIn('systemctl --user enable --now "$service_unit_name"', control)
        self.assertIn('systemctl --user restart "$service_unit_name"', control)
        self.assertIn('service_owner_marker="# Managed by community.fnos-sync"', control)
        self.assertIn('Refusing to replace a service unit not owned by the FN Sync plugin', control)
        self.assertIn("exact signatures prove that it was created by this plugin", control)
        self.assertIn("systemctl --user disable --now fnsync.service", control)
        self.assertIn('service_version_file="$service_state_dir/plugin-service-version"', control)
        self.assertIn("record_service_version", control)
        status_case = control.split('status)', 1)[1].split('bootstrap)', 1)[0]
        self.assertIn('ensure_service', status_case)
        self.assertIn('FNSYNC_LANGUAGE="$language"', control)

    def test_standalone_plugin_contains_the_client_runtime(self):
        self.assertTrue((ROOT / "runtime" / "fnsync.service").is_file())
        source_controller = ROOT.parent / "src" / "fnsync.py"
        python_runtime = ROOT / "runtime" / "fnsync.py"
        binary_runtimes = tuple((ROOT / "runtime" / "bin").glob("fn-sync-runtime-*"))
        self.assertTrue(python_runtime.is_file() or binary_runtimes)
        if source_controller.is_file() and python_runtime.is_file():
            self.assertEqual(
                python_runtime.read_bytes(),
                source_controller.read_bytes(),
            )
            self.assertFalse((ROOT / "runtime" / "ui" / "app.js").exists())
            return

        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        if binary_runtimes:
            machine = os.uname().machine
            architecture = "arm64" if machine in ("aarch64", "arm64") else "amd64"
            executable = ROOT / "runtime" / "bin" / f"fn-sync-runtime-{architecture}"
        else:
            executable = Path(sys.executable)
        result = subprocess.run(
            [str(executable), *([] if binary_runtimes else [str(python_runtime)]), "--version"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"fn-sync {manifest['version']}")
        self.assertFalse((ROOT / "runtime" / "ui" / "app.js").exists())

    def test_clean_system_reports_integrated_setup_instead_of_missing_client(self):
        with tempfile.TemporaryDirectory(prefix="fn-sync-plugin-path-") as temp:
            fake_bin = Path(temp) / "bin"
            fake_bin.mkdir()
            for command in ("dirname", "sed", "uname"):
                os.symlink(f"/usr/bin/{command}", fake_bin / command)
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
                payload["missing_dependencies"],
                "python,rclone" if (ROOT / "runtime" / "fnsync.py").exists() else "rclone",
            )

    def test_private_rclone_runtime_removes_the_system_rclone_requirement(self):
        with tempfile.TemporaryDirectory(prefix="fn-sync-managed-rclone-") as temp:
            root = Path(temp)
            home = root / "home"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for command in ("cmp", "dirname", "install", "jq", "mkdir", "python3", "sed", "uname"):
                os.symlink(f"/usr/bin/{command}", fake_bin / command)

            systemctl = fake_bin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            systemctl.chmod(0o755)

            log = root / "rclone-path"
            client = root / "client"
            client.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$FNSYNC_RCLONE\" > {log}\n"
                "printf '{\"installed\":true,\"ready\":true,\"distribution\":\"plugin\",\"missing_dependencies\":\"\",\"tasks\":[],\"connections\":[],\"error\":\"\"}\\n'\n",
                encoding="utf-8",
            )
            client.chmod(0o755)

            managed = home / ".local" / "share" / "fn-sync" / "runtime" / "rclone"
            managed.parent.mkdir(parents=True)
            managed.write_text("#!/bin/sh\necho 'rclone v1.75.0'\n", encoding="utf-8")
            managed.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "FNSYNC_BIN": str(client),
                    "HOME": str(home),
                    "PATH": str(fake_bin),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_DATA_HOME": str(home / ".local" / "share"),
                    "XDG_STATE_HOME": str(home / ".local" / "state"),
                }
            )
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
            self.assertTrue(payload["ready"], payload)
            self.assertEqual(payload["missing_dependencies"], "")
            self.assertEqual(log.read_text(encoding="utf-8").strip(), str(managed))

    def test_plugin_refuses_to_replace_a_foreign_or_symlinked_service_unit(self):
        with tempfile.TemporaryDirectory(prefix="fn-sync-foreign-unit-") as temp:
            root = Path(temp)
            home = root / "home"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            rclone = fake_bin / "rclone"
            rclone.write_text("#!/bin/sh\necho 'rclone v1.75.0'\n", encoding="utf-8")
            rclone.chmod(0o755)
            unit = home / ".config" / "systemd" / "user" / "community.fnos-sync.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("# belongs to another application\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_DATA_HOME": str(home / ".local" / "share"),
                    "XDG_STATE_HOME": str(home / ".local" / "state"),
                }
            )
            result = subprocess.run(
                [str(ROOT / "scripts" / "fn-syncctl"), "status", "en"],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 4)
            self.assertIn("not owned by the FN Sync plugin", result.stderr)
            self.assertEqual(unit.read_text(encoding="utf-8"), "# belongs to another application\n")

            unit.unlink()
            target = root / "outside.service"
            target.write_text("outside\n", encoding="utf-8")
            unit.symlink_to(target)
            result = subprocess.run(
                [str(ROOT / "scripts" / "fn-syncctl"), "status", "en"],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 4)
            self.assertIn("symbolic-link service unit", result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "outside\n")

    def test_binary_plugin_runtime_needs_no_host_python(self):
        with tempfile.TemporaryDirectory(prefix="fn-sync-binary-runtime-") as temp:
            root = Path(temp)
            plugin = root / "plugin"
            shutil.copytree(ROOT, plugin)
            (plugin / "runtime" / "fnsync.py").unlink(missing_ok=True)
            runtime_bin = plugin / "runtime" / "bin"
            runtime_bin.mkdir(parents=True, exist_ok=True)
            runtime = runtime_bin / "fn-sync-runtime-amd64"
            runtime.write_text(
                "#!/bin/sh\n"
                "case \"${1:-}\" in\n"
                "  plugin-status) printf '{\"installed\":true,\"ready\":true,\"distribution\":\"plugin\",\"missing_dependencies\":\"\",\"tasks\":[],\"connections\":[],\"error\":\"\"}\\n' ;;\n"
                "  plugin-discover) printf '{\"networks\":[],\"devices\":[],\"ports\":[]}\\n' ;;\n"
                "  *) exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            runtime.chmod(0o755)

            home = root / "home"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for command in ("cmp", "dirname", "install", "jq", "mkdir", "sed", "uname"):
                os.symlink(f"/usr/bin/{command}", fake_bin / command)
            systemctl = fake_bin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            systemctl.chmod(0o755)
            rclone = home / ".local" / "share" / "fn-sync" / "runtime" / "rclone"
            rclone.parent.mkdir(parents=True)
            rclone.write_text("#!/bin/sh\necho 'rclone v1.75.0'\n", encoding="utf-8")
            rclone.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": str(fake_bin),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_DATA_HOME": str(home / ".local" / "share"),
                    "XDG_STATE_HOME": str(home / ".local" / "state"),
                }
            )
            result = subprocess.run(
                [str(plugin / "scripts" / "fn-syncctl"), "status", "en"],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ready"], payload)
            self.assertEqual(payload["distribution"], "plugin")
            self.assertEqual(payload["missing_dependencies"], "")

            discovery = subprocess.run(
                [str(plugin / "scripts" / "fn-syncctl"), "discover"],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(discovery.returncode, 0, discovery.stderr)
            self.assertEqual(json.loads(discovery.stdout)["devices"], [])

    def test_omarchy_panel_does_not_require_the_gtk_fallback(self):
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        bar = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        self.assertNotIn("Open full client", panel)
        self.assertNotIn("打开完整客户端", panel)
        self.assertNotIn("openClient", bar)

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
