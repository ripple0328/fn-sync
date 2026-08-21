import contextlib
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.test_core import fnsync


class RuntimeBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fn-sync-runtime-")
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

    def test_streaming_forwards_sanitized_output_and_exit_code(self):
        command = [
            sys.executable,
            "-c",
            (
                'print("NOTICE: 1 / 1, 100%", flush=True); '
                'print("https://alice:secret@nas.example/path", flush=True)'
            ),
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            completed, captured = fnsync.run_streaming(command, timeout=5)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(captured, output.getvalue())
        self.assertIn("NOTICE: 1 / 1, 100%", captured)
        self.assertIn("https://***@nas.example/path", captured)
        self.assertNotIn("alice:secret", captured)

    def test_streaming_timeout_stops_a_silent_process_promptly(self):
        command = [
            sys.executable,
            "-c",
            'import time; print("started", flush=True); time.sleep(30)',
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            completed, captured = fnsync.run_streaming(command, timeout=0.2)
        self.assertEqual(completed.returncode, 124)
        self.assertIn("started", captured)
        self.assertIn("timed out", captured)

    def test_secret_service_lookup_store_and_clear_paths(self):
        success = subprocess.CompletedProcess(
            ["secret-tool"], 0, "correct horse\n", ""
        )
        with mock.patch.object(fnsync.shutil, "which", return_value="/usr/bin/secret-tool"), mock.patch.object(
            fnsync.subprocess, "run", return_value=success
        ) as run:
            self.assertEqual(fnsync.secret_tool_lookup("nas123"), "correct horse")
            self.assertTrue(
                fnsync.secret_tool_store("nas123", "Home NAS", "correct horse")
            )
            fnsync.secret_tool_clear("nas123")
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[1].kwargs["input"], "correct horse")
        self.assertIn("clear", run.call_args_list[2].args[0])

        empty = subprocess.CompletedProcess(["secret-tool"], 1, "", "locked")
        with mock.patch.object(fnsync.shutil, "which", return_value="/usr/bin/secret-tool"), mock.patch.object(
            fnsync.subprocess, "run", return_value=empty
        ):
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.secret_tool_lookup("nas123")

        with mock.patch.object(fnsync.shutil, "which", return_value=None):
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.secret_tool_lookup("nas123")
            fnsync.secret_tool_clear("nas123")

    def test_daemon_once_runs_due_tasks_and_isolates_failures(self):
        tasks = [
            {"id": "off", "name": "Off", "enabled": False},
            {"id": "ok", "name": "OK", "enabled": True, "interval_seconds": 60},
            {"id": "failed", "name": "Failed", "enabled": True, "interval_seconds": 60},
            {"id": "busy", "name": "Busy", "enabled": True, "interval_seconds": 60},
            {"id": "error", "name": "Error", "enabled": True, "interval_seconds": 60},
        ]
        results = [
            fnsync.CommandResult(0, "Complete", ["rclone"]),
            fnsync.CommandResult(7, "transfer failed", ["rclone"]),
            fnsync.TaskBusyError("busy"),
            fnsync.FnSyncError("broken authorization"),
        ]
        with mock.patch.object(fnsync.signal, "signal"), mock.patch.object(
            fnsync, "load_store", return_value={"tasks": tasks}
        ), mock.patch.object(
            fnsync, "hydrate_task", side_effect=lambda _store, task: task
        ), mock.patch.object(
            fnsync, "run_task", side_effect=results
        ) as run_task, mock.patch.object(
            fnsync.shutil, "which", return_value="/usr/bin/notify-send"
        ), mock.patch.object(
            fnsync.subprocess, "run"
        ) as notify, mock.patch.object(
            fnsync, "update_status"
        ) as update_status:
            self.assertEqual(fnsync.daemon_loop(once=True), 0)
        self.assertEqual(run_task.call_count, 4)
        notify.assert_called_once()
        self.assertIn("FN sync failed", notify.call_args.args[0])
        update_status.assert_called_once()
        self.assertEqual(update_status.call_args.args[0], "error")
        self.assertEqual(update_status.call_args.kwargs["message"], "broken authorization")

    def test_daemon_signal_handler_stops_the_idle_loop(self):
        handlers = {}

        def remember_handler(signum, handler):
            handlers[signum] = handler

        def stop_on_first_sleep(_seconds):
            handlers[fnsync.signal.SIGTERM](fnsync.signal.SIGTERM, None)

        with mock.patch.object(fnsync.signal, "signal", side_effect=remember_handler), mock.patch.object(
            fnsync, "load_store", return_value={"tasks": []}
        ), mock.patch.object(fnsync.time, "sleep", side_effect=stop_on_first_sleep):
            self.assertEqual(fnsync.daemon_loop(), 0)

    def test_ui_reports_missing_gjs_and_executes_the_packaged_entrypoint(self):
        with mock.patch.object(fnsync.shutil, "which", return_value=None):
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.cmd_ui(types.SimpleNamespace())

        with mock.patch.object(fnsync.shutil, "which", return_value="/usr/bin/gjs"), mock.patch.object(
            fnsync.os, "execv", side_effect=RuntimeError("exec intercepted")
        ) as execv:
            with self.assertRaisesRegex(RuntimeError, "exec intercepted"):
                fnsync.cmd_ui(types.SimpleNamespace())
        executable, arguments = execv.call_args.args
        self.assertEqual(executable, "/usr/bin/gjs")
        self.assertEqual(arguments[:2], ["/usr/bin/gjs", "-m"])
        self.assertTrue(arguments[2].endswith("/ui/app.js"))
        self.assertEqual(os.environ["FNSYNC_CONTROLLER"], str(Path(fnsync.__file__).resolve()))


if __name__ == "__main__":
    unittest.main()
