import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "fn-sync-omarchy-setup"
PLUGIN = ROOT / "omarchy-plugin"
BUNDLE_SETUP = ROOT / "scripts" / "install-omarchy-bundle.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fn-sync-installer-")
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.calls = self.root / "calls.jsonl"
        self._write_fake(
            "omarchy",
            """
            #!/usr/bin/env python3
            import json, os, sys
            with open(os.environ["FNSYNC_TEST_CALLS"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(["omarchy", *sys.argv[1:]]) + "\\n")
            raise SystemExit(0)
            """,
        )
        self._write_fake(
            "omarchy-shell",
            """
            #!/usr/bin/env python3
            import json, os, sys
            with open(os.environ["FNSYNC_TEST_CALLS"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(["omarchy-shell", *sys.argv[1:]]) + "\\n")
            raise SystemExit(0)
            """,
        )
        self._write_fake(
            "systemctl",
            """
            #!/usr/bin/env python3
            import json, os, sys
            with open(os.environ["FNSYNC_TEST_CALLS"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(["systemctl", *sys.argv[1:]]) + "\\n")
            raise SystemExit(0)
            """,
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.root / "home"),
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "FNSYNC_PLUGIN_SOURCE": str(PLUGIN),
                "FNSYNC_TEST_CALLS": str(self.calls),
                "PATH": f"{self.bin_dir}:{os.environ.get('PATH', '')}",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_fake(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def run_setup(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(SETUP), *args],
            text=True,
            capture_output=True,
            env=self.env,
            timeout=20,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def test_copy_only_installs_every_runtime_file_and_update_backs_up(self):
        self.run_setup("--copy-only")
        target = self.root / "config" / "omarchy" / "plugins" / "community.fnos-sync"
        expected = {
            "manifest.json",
            "BarWidget.qml",
            "Panel.qml",
            "PanelPageHeader.qml",
            "FnSyncIcon.qml",
            "README.md",
            "README.zh-CN.md",
            "LICENSE",
            "preview.png",
            "assets/fn-sync-symbolic.png",
            "scripts/fn-syncctl",
            "scripts/fn_sync_discover.py",
            "runtime/fnsync.py",
            "runtime/ui/app.js",
            "runtime/fnsync.service",
        }
        actual = {
            str(path.relative_to(target))
            for path in target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, expected)
        self.assertEqual((target / "scripts" / "fn-syncctl").stat().st_mode & 0o777, 0o755)

        self.run_setup("--copy-only", expected=1)
        self.run_setup("--update", "--copy-only")
        backups = list((self.root / "state" / "fn-sync" / "plugin-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "manifest.json").exists())

    def test_normal_setup_enables_service_rescans_and_enables_plugin(self):
        self.run_setup()
        calls = [
            json.loads(line)
            for line in self.calls.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn(["omarchy", "plugin", "validate", str(PLUGIN)], calls)
        self.assertIn(["systemctl", "--user", "daemon-reload"], calls)
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", "fnsync.service"], calls
        )
        self.assertIn(["omarchy-shell", "shell", "rescanPlugins"], calls)
        self.assertIn(
            [
                "omarchy",
                "plugin",
                "enable",
                "community.fnos-sync",
                "--section",
                "right",
            ],
            calls,
        )

    def test_bundle_installer_adds_dependencies_package_and_plugin_in_one_run(self):
        bundle = self.root / "bundle"
        (bundle / "scripts").mkdir(parents=True)
        (bundle / "dist").mkdir()
        (bundle / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        installer = bundle / "scripts" / BUNDLE_SETUP.name
        installer.write_text(BUNDLE_SETUP.read_text(encoding="utf-8"), encoding="utf-8")
        installer.chmod(0o755)
        package = bundle / "dist" / "fn-sync-9.9.9-1-any.pkg.tar.zst"
        package.write_bytes(b"package")
        self._write_fake(
            "sudo",
            """
            #!/usr/bin/env python3
            import json, os, sys
            with open(os.environ["FNSYNC_TEST_CALLS"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(["sudo", *sys.argv[1:]]) + "\\n")
            raise SystemExit(0)
            """,
        )
        self._write_fake(
            "fn-sync-omarchy-setup",
            """
            #!/usr/bin/env python3
            import json, os, sys
            with open(os.environ["FNSYNC_TEST_CALLS"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(["fn-sync-omarchy-setup", *sys.argv[1:]]) + "\\n")
            raise SystemExit(0)
            """,
        )

        result = subprocess.run(
            [str(installer)],
            text=True,
            capture_output=True,
            env=self.env,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [
            json.loads(line)
            for line in self.calls.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn(
            ["omarchy", "pkg", "add", "rclone", "python", "gjs", "gtk4", "libsecret", "libnotify"],
            calls,
        )
        self.assertIn(
            ["sudo", "pacman", "-U", "--needed", "--noconfirm", str(package)],
            calls,
        )
        self.assertIn(["fn-sync-omarchy-setup", "--update"], calls)


if __name__ == "__main__":
    unittest.main()
