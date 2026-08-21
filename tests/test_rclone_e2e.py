import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src" / "fnsync.py"
RCLONE = shutil.which("rclone")


@unittest.skipUnless(RCLONE, "rclone is required for the local WebDAV end-to-end test")
class RcloneWebDavEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fn-sync-webdav-e2e-")
        self.root = Path(self.temp.name)
        self.remote_root = self.root / "remote"
        self.remote_root.mkdir()
        self.port = self._free_port()
        self.server = subprocess.Popen(
            [
                str(RCLONE),
                "serve",
                "webdav",
                str(self.remote_root),
                "--addr",
                f"127.0.0.1:{self.port}",
                "--user",
                "alice",
                "--pass",
                "test-password",
                # The test intentionally mutates the served filesystem directly.
                # Disable VFS directory caching so WebDAV observes those changes.
                "--dir-cache-time",
                "0s",
                "--log-level",
                "ERROR",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._wait_for_server()

        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        secret_tool = fake_bin / "secret-tool"
        secret_tool.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        secret_tool.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "FNSYNC_RCLONE": str(RCLONE),
                "FNSYNC_LANGUAGE": "en",
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            }
        )

    def tearDown(self):
        self.server.terminate()
        try:
            self.server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.communicate(timeout=5)
        self.temp.cleanup()

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _wait_for_server(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                stdout, stderr = self.server.communicate()
                self.fail(f"rclone WebDAV server exited early:\n{stdout}\n{stderr}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("rclone WebDAV server did not become ready")

    def cli(
        self,
        *args: str,
        input_text: str | None = None,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(CONTROLLER), *args],
            input=input_text,
            text=True,
            capture_output=True,
            env=self.env,
            timeout=90,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def add_task(
        self, connection_id: str, name: str, mode: str, local: Path, remote: str
    ) -> dict:
        return json.loads(
            self.cli(
                "task",
                "add",
                "--name",
                name,
                "--mode",
                mode,
                "--connection",
                connection_id,
                "--local",
                str(local),
                "--remote-path",
                remote,
            ).stdout
        )

    def test_real_webdav_two_way_safety_and_non_deleting_one_way_modes(self):
        connection = json.loads(
            self.cli(
                "connection",
                "add",
                "--name",
                "Local WebDAV",
                "--url",
                f"http://127.0.0.1:{self.port}/",
                "--username",
                "alice",
                "--password-stdin",
                "--allow-http",
                input_text="test-password\n",
            ).stdout
        )
        connection_id = connection["id"]

        local_two_way = self.root / "local" / "documents"
        local_two_way.mkdir(parents=True)
        (local_two_way / "from-linux.txt").write_text("linux\n", encoding="utf-8")
        remote_two_way = self.remote_root / "Sync" / "Documents"
        remote_two_way.mkdir(parents=True)
        (remote_two_way / "from-nas.txt").write_text("nas\n", encoding="utf-8")
        two_way = self.add_task(
            connection_id, "Documents", "two-way", local_two_way, "Sync/Documents"
        )

        self.cli("task", "preview", two_way["id"], "--winner", "local", "--json")
        self.cli(
            "task",
            "initialize",
            two_way["id"],
            "--winner",
            "local",
            "--apply",
            "--json",
        )
        self.assertEqual(
            (local_two_way / "from-nas.txt").read_text(encoding="utf-8"), "nas\n"
        )
        self.assertEqual(
            (remote_two_way / "from-linux.txt").read_text(encoding="utf-8"),
            "linux\n",
        )

        (local_two_way / "incremental.txt").write_text("next\n", encoding="utf-8")
        self.cli("task", "run", two_way["id"], "--json")
        self.assertEqual(
            (remote_two_way / "incremental.txt").read_text(encoding="utf-8"),
            "next\n",
        )

        (remote_two_way / "FN_SYNC_ACCESS_TEST").unlink()
        stopped = self.cli("task", "run", two_way["id"], expected=2)
        self.assertIn("NAS FN sync marker is missing", stopped.stderr)
        saved_tasks = json.loads(self.cli("task", "list", "--json").stdout)
        self.assertFalse(saved_tasks[0]["enabled"])
        self.cli("task", "repair-access", two_way["id"], "--resume", "--json")
        self.assertTrue((remote_two_way / "FN_SYNC_ACCESS_TEST").exists())

        upload_local = self.root / "local" / "uploads"
        upload_local.mkdir(parents=True)
        (upload_local / "keep-on-nas.txt").write_text("upload\n", encoding="utf-8")
        upload = self.add_task(
            connection_id, "Uploads", "upload-only", upload_local, "Sync/Uploads"
        )
        self.cli("task", "run", upload["id"], "--json")
        uploaded = self.remote_root / "Sync" / "Uploads" / "keep-on-nas.txt"
        self.assertTrue(uploaded.exists())
        (upload_local / "keep-on-nas.txt").unlink()
        self.cli("task", "run", upload["id"], "--json")
        self.assertTrue(uploaded.exists())

        remote_download = self.remote_root / "Sync" / "Downloads"
        remote_download.mkdir(parents=True)
        (remote_download / "keep-on-linux.txt").write_text("download\n", encoding="utf-8")
        download_local = self.root / "local" / "downloads"
        download = self.add_task(
            connection_id,
            "Downloads",
            "download-only",
            download_local,
            "Sync/Downloads",
        )
        self.cli("task", "run", download["id"], "--json")
        downloaded = download_local / "keep-on-linux.txt"
        self.assertTrue(downloaded.exists())
        (remote_download / "keep-on-linux.txt").unlink()
        self.cli("task", "run", download["id"], "--json")
        self.assertTrue(downloaded.exists())
