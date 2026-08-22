import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.test_core import fnsync


class SecurityBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fn-sync-bounds-")
        self.root = Path(self.temp.name)
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "FNSYNC_LANGUAGE": "en",
            },
        )
        self.env_patch.start()
        fnsync.ensure_runtime_dirs()

    def tearDown(self):
        self.env_patch.stop()
        self.temp.cleanup()

    def test_strict_process_caps_stdout_stderr_and_single_lines_while_running(self):
        stdout = fnsync.run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
            timeout=5,
            stdout_limit=1024,
            stderr_limit=1024,
        )
        self.assertEqual(stdout.returncode, 125)
        self.assertEqual(stdout.overflow, "stdout")
        self.assertLessEqual(len(stdout.stdout.encode()), 1024)

        stderr = fnsync.run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stderr.write('y' * 1000000)"],
            timeout=5,
            stdout_limit=1024,
            stderr_limit=2048,
        )
        self.assertEqual(stderr.returncode, 125)
        self.assertEqual(stderr.overflow, "stderr")
        self.assertLessEqual(len(stderr.stderr.encode()), 2048)

    def test_long_sync_retains_a_tail_and_counts_all_preview_actions(self):
        count = 5000
        script = (
            "import sys\n"
            f"for i in range({count}):\n"
            " print(f'NOTICE: file-{i}: Skipped copy as --dry-run is set')\n"
        )
        result = fnsync.run_bounded_process(
            [sys.executable, "-c", script],
            timeout=10,
            stdout_limit=4096,
            stderr_limit=1024,
            strict_output=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.planned_changes, count)
        self.assertLessEqual(len(result.stdout.encode()), 4096)
        self.assertIn(f"file-{count - 1}", result.stdout)

    def test_folder_and_configuration_collections_have_hard_limits(self):
        folders = [
            {"Name": f"folder-{index}", "IsDir": True}
            for index in range(fnsync.MAX_FOLDER_ITEMS + 1)
        ]
        with self.assertRaisesRegex(fnsync.FnSyncError, "too many items"):
            fnsync._folder_items(json.dumps(folders), "")

        tasks_path = fnsync.runtime_paths()["tasks"]
        tasks_path.write_bytes(b" " * (fnsync.MAX_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(fnsync.FnSyncError, "oversized file"):
            fnsync.load_store()

        tasks_path.unlink()
        target = self.root / "outside.json"
        target.write_text(json.dumps(fnsync.empty_store()), encoding="utf-8")
        tasks_path.symlink_to(target)
        with self.assertRaises(fnsync.FnSyncError):
            fnsync.load_store()

    def test_path_identifiers_and_marker_symlinks_are_rejected(self):
        connection = {
            "id": "../escape",
            "name": "NAS",
            "url": "https://nas.example/",
            "username": "alice",
            "remote_name": "fnsync_nas_safe",
            "credential_backend": "rclone-obscured",
            "secret_attribute": "connection",
            "secret_id": "safe",
            "allow_http": False,
            "insecure_skip_verify": False,
        }
        with self.assertRaisesRegex(fnsync.FnSyncError, "ID is invalid"):
            fnsync.save_store({"version": 2, "connections": [connection], "tasks": []})

        local = self.root / "sync"
        local.mkdir()
        outside = self.root / "outside-marker"
        outside.write_text("do not overwrite", encoding="utf-8")
        (local / fnsync.ACCESS_MARKER).symlink_to(outside)
        task = {"id": "task123", "local_path": str(local), "mode": "two-way"}
        with self.assertRaisesRegex(fnsync.AccessMarkerError, "symbolic-link marker"):
            fnsync.ensure_access_markers(task)
        self.assertEqual(outside.read_text(encoding="utf-8"), "do not overwrite")

        outside_log = self.root / "outside-log"
        outside_log.write_text("do not append", encoding="utf-8")
        log = fnsync.runtime_paths()["logs"] / "task123.log"
        log.symlink_to(outside_log)
        with self.assertRaisesRegex(fnsync.FnSyncError, "non-regular task log"):
            fnsync.append_task_log(log, "new data")
        self.assertEqual(outside_log.read_text(encoding="utf-8"), "do not append")

    def test_log_command_reads_only_a_bounded_tail(self):
        local = self.root / "sync"
        local.mkdir()
        connection = {
            "id": "nas123",
            "name": "NAS",
            "url": "https://nas.example/",
            "username": "alice",
            "remote_name": "fnsync_nas_nas123",
            "credential_backend": "rclone-obscured",
            "secret_attribute": "connection",
            "secret_id": "nas123",
            "allow_http": False,
            "insecure_skip_verify": False,
        }
        task = {
            "id": "task123",
            "name": "Task",
            "connection_id": "nas123",
            "enabled": False,
            "mode": "upload-only",
            "local_path": str(local),
            "remote_path": "Sync",
            "interval_seconds": 300,
            "bwlimit": None,
            "filters": [],
            "initialized": True,
        }
        fnsync.save_store({"version": 2, "connections": [connection], "tasks": [task]})
        log = fnsync.runtime_paths()["logs"] / "task123.log"
        log.write_bytes(b"old\n" + b"x" * (fnsync.MAX_CAPTURE_BYTES + 100) + b"\nlast\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(fnsync.cmd_logs(types.SimpleNamespace(task_id="task123", lines=1)), 0)
        self.assertEqual(output.getvalue().strip(), "last")

    def test_plugin_status_is_emitted_as_one_bounded_controller_payload(self):
        fnsync.save_store(fnsync.empty_store())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                fnsync.cmd_plugin_status(types.SimpleNamespace(distribution="plugin")),
                0,
            )
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["installed"])
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["distribution"], "plugin")
        self.assertEqual(payload["tasks"], [])
        self.assertEqual(payload["connections"], [])


if __name__ == "__main__":
    unittest.main()
