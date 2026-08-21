import ast
import json
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionContractTests(unittest.TestCase):
    def test_all_version_sources_match(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        source = ast.parse((ROOT / "src" / "fnsync.py").read_text(encoding="utf-8"))
        app_version = next(
            node.value.value
            for node in source.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)
            and isinstance(node.value, ast.Constant)
        )
        manifest = json.loads(
            (ROOT / "omarchy-plugin" / "manifest.json").read_text(encoding="utf-8")
        )
        pkgbuild = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(
            encoding="utf-8"
        )
        self.assertEqual(app_version, version)
        self.assertEqual(manifest["version"], version)
        self.assertRegex(pkgbuild, rf"(?m)^pkgver={re.escape(version)}$")

    def test_package_keeps_cli_name_but_localizes_display_name(self):
        desktop = (ROOT / "packaging" / "fnsync.desktop").read_text(encoding="utf-8")
        app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        manifest = json.loads(
            (ROOT / "omarchy-plugin" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("Name=FN sync", desktop)
        self.assertIn("Name[zh]=飞牛", desktop)
        self.assertIn("Exec=fn-sync ui", desktop)
        self.assertIn('title: t("FN sync", "飞牛")', app)
        self.assertEqual(manifest["name"], "FN sync")
        self.assertEqual(manifest["barWidget"]["displayName"], "FN sync")
        self.assertIn("fn-sync", manifest["barWidget"]["aliases"])

    def test_package_bundles_the_complete_plugin_and_setup_helper(self):
        for template in ("arch", "aur"):
            pkgbuild = (ROOT / "packaging" / template / "PKGBUILD").read_text(
                encoding="utf-8"
            )
            for relative in (
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
            ):
                self.assertIn(f"omarchy-plugin/{relative}", pkgbuild)
            self.assertIn("scripts/fn-sync-omarchy-setup", pkgbuild)

    def test_release_source_archive_contains_the_tagged_tree(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        prefix = f"fn-sync-{version}"
        with tempfile.TemporaryDirectory(prefix="fn-sync-release-test-") as temp:
            archive = Path(temp) / f"{prefix}.tar.gz"
            result = subprocess.run(
                [str(ROOT / "scripts" / "release-source.sh"), "HEAD", str(archive)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(archive.stat().st_size, 1024)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o644)
            with tarfile.open(archive, "r:gz") as handle:
                names = set(handle.getnames())
                self.assertIn(f"{prefix}/VERSION", names)
                self.assertIn(f"{prefix}/README.md", names)
                self.assertIn(f"{prefix}/README.zh-CN.md", names)
                self.assertIn(f"{prefix}/src/fnsync.py", names)
                self.assertIn(f"{prefix}/omarchy-plugin/PanelPageHeader.qml", names)
                self.assertIn(f"{prefix}/omarchy-plugin/README.zh-CN.md", names)

    def test_plugin_repository_contract_has_no_symlinks(self):
        plugin = ROOT / "omarchy-plugin"
        manifest = json.loads((plugin / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "community.fnos-sync")
        for entry_point in manifest["entryPoints"].values():
            self.assertTrue((plugin / entry_point).is_file())
        self.assertFalse(any(path.is_symlink() for path in plugin.rglob("*")))

    def test_services_launch_the_stable_command(self):
        packaged = (ROOT / "packaging" / "fnsync.service").read_text(encoding="utf-8")
        local = (ROOT / "packaging" / "fnsync-local.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/fn-sync daemon", packaged)
        self.assertIn("ExecStart=%h/.local/bin/fn-sync daemon", local)
        self.assertIn("NoNewPrivileges=true", packaged)
        self.assertIn("PrivateTmp=true", packaged)

    def test_package_verifier_executes_the_bundled_controller(self):
        verifier = (ROOT / "scripts" / "verify-package.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('bsdtar -xf "$package_path" -C "$package_root"', verifier)
        self.assertIn('plugin_root="$temp_dir/plugin-root"', verifier)
        self.assertIn(
            'python3 "$package_root/usr/lib/fn-sync/fnsync.py" --version',
            verifier,
        )


if __name__ == "__main__":
    unittest.main()
