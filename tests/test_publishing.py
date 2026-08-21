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

    def test_ci_enforces_lint_transfer_and_package_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for required in (
            "ruff check",
            "shellcheck",
            "rhysd/actionlint:1.7.12",
            "tests.test_rclone_e2e",
            "./scripts/build-packages.sh",
            "./scripts/verify-package.sh",
            "omarchy-plugin-validate",
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
        ):
            self.assertIn(required, workflow)

    def test_plugin_subtree_uses_a_write_scoped_deploy_key(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-plugin.yml").read_text(
            encoding="utf-8"
        )
        for required in (
            "secrets.PLUGIN_DEPLOY_KEY",
            "git subtree split --prefix=omarchy-plugin",
            "ripple0328/omarchy-fn-sync.git",
            "git push plugin plugin-release:main",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
