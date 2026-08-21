import base64
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublishingContractTests(unittest.TestCase):
    def test_documentation_images_are_present(self):
        for readme in (ROOT / "README.md", ROOT / "omarchy-plugin" / "README.md"):
            content = readme.read_text(encoding="utf-8")
            image_paths = re.findall(r"!\[[^]]*]\(([^)]+)\)", content)
            self.assertTrue(image_paths, f"{readme} should contain an interface image")
            for image_path in image_paths:
                if "://" in image_path:
                    continue
                resolved = readme.parent / image_path
                self.assertTrue(resolved.is_file(), f"missing documentation image: {resolved}")

    def test_plugin_readme_documents_install_update_and_removal(self):
        readme = (ROOT / "omarchy-plugin" / "README.md").read_text(encoding="utf-8")
        for required in (
            "## Installation",
            "fn-sync-omarchy-setup",
            "omarchy plugin update community.fnos-sync --yes",
            "## Removal",
            "omarchy plugin remove community.fnos-sync --yes",
            "systemctl --user disable --now fnsync.service",
            "omarchy pkg drop fn-sync",
            "does not delete either synchronized folder",
            "task configuration and logs remain",
        ):
            self.assertIn(required, readme)

    def test_ci_enforces_lint_transfer_and_package_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for required in (
            "ruff check",
            "shellcheck",
            "rhysd/actionlint:1.7.12",
            ".github/workflows/publish-aur.yml",
            "tests.test_rclone_e2e",
            "./scripts/build-packages.sh",
            "./scripts/verify-package.sh",
            "omarchy-plugin-validate",
            "pacman-contrib",
        ):
            self.assertIn(required, workflow)

    def test_release_publishes_github_and_gated_aur_artifacts(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for required in (
            'tags: ["v*"]',
            "gh release create",
            "vars.AUR_PUBLISH_ENABLED == 'true'",
            "secrets.AUR_SSH_PRIVATE_KEY",
            "ssh://aur@aur.archlinux.org/fn-sync.git",
            "PKGBUILD .SRCINFO fn-sync.install",
            "git push origin master",
            "test -d .git",
            "UserKnownHostsFile=$GITHUB_WORKSPACE/.aur-ssh/known_hosts",
            "-i $GITHUB_WORKSPACE/.aur-ssh/aur",
            "HostKeyAlgorithms=ssh-ed25519",
            ".github/aur-known-hosts",
            "pacman-contrib",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn("ssh-keyscan", workflow)

        install_position = workflow.index("Install release dependencies")
        checkout_position = workflow.index("actions/checkout@v7")
        self.assertLess(install_position, checkout_position)

    def test_manual_aur_recovery_uses_the_verified_release_source(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-aur.yml").read_text(
            encoding="utf-8"
        )
        for required in (
            "workflow_dispatch",
            "vars.AUR_PUBLISH_ENABLED == 'true'",
            "secrets.AUR_SSH_PRIVATE_KEY",
            "releases/download/$release_tag/fn-sync-$version.tar.gz",
            "tar -tzf",
            "./scripts/prepare-aur.sh",
            'useradd --create-home builder',
            'chown -R builder:builder "$GITHUB_WORKSPACE"',
            "runuser -u builder",
            "makepkg --verifysource",
            "UserKnownHostsFile=$GITHUB_WORKSPACE/.aur-ssh/known_hosts",
            "-i $GITHUB_WORKSPACE/.aur-ssh/aur",
            "HostKeyAlgorithms=ssh-ed25519",
            ".github/aur-known-hosts",
            "git push origin master",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn("ssh-keyscan", workflow)

    def test_aur_host_key_is_pinned_to_arch_linux_infrastructure(self):
        known_hosts = (ROOT / ".github" / "aur-known-hosts").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "github.com/archlinux/infrastructure/blob/main/docs/ssh-known_hosts.txt",
            known_hosts,
        )
        host_keys = [
            line for line in known_hosts.splitlines() if line and not line.startswith("#")
        ]
        self.assertEqual(len(host_keys), 1)
        host, algorithm, encoded_key = host_keys[0].split()
        self.assertEqual(host, "aur.archlinux.org")
        self.assertEqual(algorithm, "ssh-ed25519")
        digest = hashlib.sha256(base64.b64decode(encoded_key, validate=True)).digest()
        fingerprint = base64.b64encode(digest).decode("ascii").rstrip("=")
        self.assertEqual(
            fingerprint,
            "RFzBCUItH9LZS0cKB5UE6ceAYhBD5C8GeOBip8Z11+4",
        )

    def test_package_verifier_reports_its_bsdtar_dependency(self):
        verifier = (ROOT / "scripts" / "verify-package.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("command -v bsdtar", verifier)
        self.assertIn("install libarchive", verifier)

    def test_plugin_subtree_uses_a_write_scoped_deploy_key(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-plugin.yml").read_text(
            encoding="utf-8"
        )
        for required in (
            "secrets.PLUGIN_DEPLOY_KEY",
            "omarchy-plugin/PanelPageHeader.qml",
            "git subtree split --prefix=omarchy-plugin",
            "ripple0328/omarchy-fn-sync.git",
            "git push plugin plugin-release:main",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
