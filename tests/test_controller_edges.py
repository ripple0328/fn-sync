import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "fnsync.py"
SPEC = importlib.util.spec_from_file_location("fnsync_edges_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
fnsync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fnsync
SPEC.loader.exec_module(fnsync)


class ControllerEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fnsync-edge-test-")
        self.root = Path(self.temp.name)
        self.saved_env = {
            key: os.environ.get(key)
            for key in (
                "XDG_CONFIG_HOME",
                "XDG_STATE_HOME",
                "XDG_DATA_HOME",
                "FNSYNC_DISABLE_SECRET_SERVICE",
                "FNSYNC_LANGUAGE",
            )
        }
        os.environ["XDG_CONFIG_HOME"] = str(self.root / "config")
        os.environ["XDG_STATE_HOME"] = str(self.root / "state")
        os.environ["XDG_DATA_HOME"] = str(self.root / "data")
        os.environ["FNSYNC_LANGUAGE"] = "en"
        os.environ.pop("FNSYNC_DISABLE_SECRET_SERVICE", None)
        fnsync.ensure_runtime_dirs()

    def tearDown(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def connection(self, **overrides):
        value = {
            "id": "nas123",
            "name": "Home NAS",
            "url": "https://nas.example:5006/",
            "username": "alice",
            "remote_name": "fnsync_nas_nas123",
            "credential_backend": "rclone-obscured",
            "secret_attribute": "connection",
            "secret_id": "nas123",
            "allow_http": False,
            "insecure_skip_verify": False,
        }
        value.update(overrides)
        return value

    def task(self, task_id="task123", **overrides):
        value = {
            "id": task_id,
            "name": f"Task {task_id}",
            "connection_id": "nas123",
            "enabled": True,
            "mode": "upload-only",
            "local_path": str(self.root / task_id),
            "remote_path": f"Sync/{task_id}",
            "interval_seconds": 300,
            "bwlimit": None,
            "filters": [],
            "initialized": True,
        }
        value.update(overrides)
        return value

    def store(self, tasks=None, connections=None):
        return {
            "version": fnsync.CONFIG_VERSION,
            "connections": list(connections or [self.connection()]),
            "tasks": list(tasks or []),
        }

    def write_remote(self, connection=None):
        connection = connection or self.connection()
        parser = fnsync._load_rclone_config()
        parser[connection["remote_name"]] = {
            "type": "webdav",
            "url": connection["url"],
            "vendor": "other",
            "user": connection["username"],
            "pass": "obscured",
        }
        fnsync._write_rclone_config(parser)

    def test_load_store_rejects_corrupt_and_unsupported_configuration(self):
        path = fnsync.runtime_paths()["tasks"]
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(fnsync.FnSyncError, "Could not read"):
            fnsync.load_store()

        path.write_text(
            json.dumps({"version": 99, "connections": [], "tasks": []}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(fnsync.FnSyncError, "version is not supported"):
            fnsync.load_store()

    def test_rclone_version_and_minimum_version_fail_closed(self):
        invalid = fnsync.BoundedProcessResult(0, "unknown", "")
        with mock.patch.object(fnsync, "run_bounded_process", return_value=invalid):
            with self.assertRaisesRegex(fnsync.FnSyncError, "determine the rclone version"):
                fnsync.rclone_version("rclone")

        timed_out = fnsync.BoundedProcessResult(124, "", "", timed_out=True)
        with mock.patch.object(fnsync, "run_bounded_process", return_value=timed_out):
            with self.assertRaisesRegex(fnsync.FnSyncError, "Could not run rclone"):
                fnsync.rclone_version("rclone")

        with mock.patch.object(fnsync, "rclone_binary", return_value="rclone"), mock.patch.object(
            fnsync, "rclone_version", return_value=(1, 65, 2)
        ):
            with self.assertRaisesRegex(fnsync.FnSyncError, "too old"):
                fnsync.require_rclone()

    def test_secret_service_store_is_optional_and_fail_closed(self):
        os.environ["FNSYNC_DISABLE_SECRET_SERVICE"] = "1"
        self.assertFalse(fnsync.secret_tool_store("nas123", "NAS", "secret"))
        os.environ.pop("FNSYNC_DISABLE_SECRET_SERVICE")

        with mock.patch.object(fnsync.shutil, "which", return_value=None):
            self.assertFalse(fnsync.secret_tool_store("nas123", "NAS", "secret"))

        success = fnsync.BoundedProcessResult(0, "", "")
        with mock.patch.object(fnsync.shutil, "which", return_value="secret-tool"), mock.patch.object(
            fnsync, "run_bounded_process", return_value=success
        ) as run:
            self.assertTrue(fnsync.secret_tool_store("nas123", "NAS", "secret"))
        self.assertEqual(run.call_args.kwargs["input_text"], "secret")

        with mock.patch.object(fnsync.shutil, "which", return_value="secret-tool"), mock.patch.object(
            fnsync, "run_bounded_process", side_effect=fnsync.FnSyncError("keyring unavailable")
        ):
            self.assertFalse(fnsync.secret_tool_store("nas123", "NAS", "secret"))

    def test_remote_test_uses_task_remote_and_tls_policy(self):
        task = self.task(
            mode="two-way",
            remote_name="fnsync_nas_nas123",
            insecure_skip_verify=True,
        )
        expected = fnsync.CommandResult(0, "folders", ["rclone", "lsd"])
        with mock.patch.object(fnsync, "run_rclone", return_value=expected) as run:
            self.assertIs(fnsync.test_remote(task), expected)
        args = run.call_args.args[1]
        self.assertEqual(args[:2], ["lsd", "fnsync_nas_nas123:Sync/task123"])
        self.assertIn("--no-check-certificate", args)
        self.assertEqual(run.call_args.kwargs["status_action"], "connection-test")

    def test_doctor_reports_supported_and_missing_rclone(self):
        output = io.StringIO()
        with mock.patch.object(fnsync, "rclone_version", return_value=(1, 72, 1)), redirect_stdout(
            output
        ):
            self.assertEqual(fnsync.cmd_doctor(types.SimpleNamespace(json=True)), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["rclone"], "1.72.1")
        self.assertTrue(payload["rclone_supported"])

        output = io.StringIO()
        with mock.patch.object(
            fnsync, "rclone_version", side_effect=fnsync.FnSyncError("missing rclone")
        ), redirect_stdout(output):
            self.assertEqual(fnsync.cmd_doctor(types.SimpleNamespace(json=True)), 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["rclone_error"], "missing rclone")

    def test_connection_update_without_password_updates_remote_and_invalidates_check(self):
        task = self.task(
            mode="two-way",
            initialized=False,
            first_sync_check={"conflict_winner": "local"},
        )
        connection = self.connection()
        fnsync.save_store(self.store([task], [connection]))
        self.write_remote(connection)
        args = types.SimpleNamespace(
            connection_id="nas123",
            name="Renamed NAS",
            url="https://new-nas.example:5006/",
            username="bob",
            password_stdin=False,
            allow_http=None,
            insecure_skip_verify=True,
        )
        with mock.patch.object(fnsync, "password_from_args", return_value=None), mock.patch.object(
            fnsync, "verify_connection_update"
        ), redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(fnsync.cmd_connection_update(args), 0)
        saved = fnsync.load_store()
        self.assertEqual(saved["connections"][0]["name"], "Renamed NAS")
        self.assertEqual(saved["connections"][0]["username"], "bob")
        self.assertNotIn("first_sync_check", saved["tasks"][0])
        parser = fnsync._load_rclone_config()
        self.assertEqual(parser[connection["remote_name"]]["url"], args.url)
        self.assertEqual(parser[connection["remote_name"]]["user"], "bob")

    def test_connection_password_change_clears_displaced_keyring_secret(self):
        connection = self.connection(credential_backend="secret-service")
        task = self.task(mode="two-way", initialized=False, first_sync_check={"conflict_winner": "nas"})
        fnsync.save_store(self.store([task], [connection]))
        args = types.SimpleNamespace(
            connection_id="nas123",
            name=None,
            url=None,
            username=None,
            password_stdin=True,
            allow_http=None,
            insecure_skip_verify=None,
        )
        with mock.patch.object(fnsync, "password_from_args", return_value="new-password"), mock.patch.object(
            fnsync, "verify_connection_update"
        ), mock.patch.object(
            fnsync, "store_remote", return_value="rclone-obscured"
        ), mock.patch.object(fnsync, "secret_tool_clear") as clear, redirect_stdout(io.StringIO()):
            self.assertEqual(fnsync.cmd_connection_update(args), 0)
        clear.assert_called_once_with("nas123", "connection")
        saved = fnsync.load_store()
        self.assertEqual(saved["connections"][0]["credential_backend"], "rclone-obscured")
        self.assertNotIn("first_sync_check", saved["tasks"][0])

    def test_connection_update_verifies_before_mutating_saved_state(self):
        connection = self.connection()
        fnsync.save_store(self.store([], [connection]))
        self.write_remote(connection)
        before_store = fnsync.runtime_paths()["tasks"].read_bytes()
        before_remote = fnsync.runtime_paths()["rclone"].read_bytes()
        args = types.SimpleNamespace(
            connection_id="nas123",
            name="Changed",
            url="https://unreachable.example:5006/",
            username="bob",
            password_stdin=True,
            allow_http=None,
            insecure_skip_verify=None,
        )
        with mock.patch.object(fnsync, "password_from_args", return_value="new-password"), mock.patch.object(
            fnsync,
            "verify_connection_update",
            side_effect=fnsync.FnSyncError("connection refused"),
        ), mock.patch.object(fnsync, "store_remote") as store_remote:
            with self.assertRaisesRegex(fnsync.FnSyncError, "connection refused"):
                fnsync.cmd_connection_update(args)
        store_remote.assert_not_called()
        self.assertEqual(fnsync.runtime_paths()["tasks"].read_bytes(), before_store)
        self.assertEqual(fnsync.runtime_paths()["rclone"].read_bytes(), before_remote)

    def test_task_add_with_saved_connection_writes_filter_and_safe_defaults(self):
        fnsync.save_store(self.store())
        local = self.root / "projects"
        args = types.SimpleNamespace(
            local=str(local),
            remote_path="Projects/Linux",
            interval=600,
            bwlimit="8M",
            name="Linux projects",
            filter=["- cache/**"],
            mode="upload-only",
            connection="nas123",
            url=None,
            username=None,
            password_stdin=False,
            connection_name=None,
            allow_http=False,
            insecure_skip_verify=False,
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(fnsync.cmd_task_add(args), 0)
        task = fnsync.load_store()["tasks"][0]
        self.assertFalse(task["enabled"])
        self.assertTrue(task["initialized"])
        self.assertEqual(task["bwlimit"], "8M")
        rules = (fnsync.runtime_paths()["filters"] / f"{task['id']}.rules").read_text(
            encoding="utf-8"
        )
        self.assertIn("- cache/**", rules)

    def test_sync_now_reports_success_failure_and_skips_paused_tasks(self):
        tasks = [
            self.task("good"),
            self.task("broken"),
            self.task("paused", enabled=False),
        ]
        fnsync.save_store(self.store(tasks))
        output = io.StringIO()
        with mock.patch.object(
            fnsync,
            "run_task",
            side_effect=[
                fnsync.CommandResult(0, "complete", ["rclone"]),
                fnsync.FnSyncError("NAS unavailable"),
            ],
        ) as run, redirect_stdout(output):
            self.assertEqual(fnsync.cmd_sync_now(types.SimpleNamespace(json=True)), 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["results"][0]["ok"])
        self.assertEqual(payload["results"][1]["message"], "NAS unavailable")
        self.assertEqual(run.call_count, 2)

    def test_folder_listing_text_and_invalid_payload_paths(self):
        output = io.StringIO()
        folders = [{"name": "Projects", "path": "Home/Projects"}]
        with redirect_stdout(output):
            self.assertEqual(fnsync.print_folder_listing("Home", folders, json_output=False), 0)
        self.assertEqual(output.getvalue().strip(), "Home/Projects")

        with self.assertRaisesRegex(fnsync.FnSyncError, "invalid folder listing"):
            fnsync._folder_items("not-json", "")
        with self.assertRaisesRegex(fnsync.FnSyncError, "invalid folder listing"):
            fnsync._folder_items('{"Name":"not-a-list"}', "")

    def test_security_validators_reject_broad_paths_and_unsafe_input(self):
        with self.assertRaisesRegex(fnsync.FnSyncError, "entire home directory"):
            fnsync.validate_local_path(str(Path.home()))
        with self.assertRaisesRegex(fnsync.FnSyncError, "too broad"):
            fnsync.validate_local_path("/var")
        with self.assertRaisesRegex(fnsync.FnSyncError, "cannot be empty"):
            fnsync.validate_remote_path("/")
        with self.assertRaisesRegex(fnsync.FnSyncError, "invalid characters"):
            fnsync.validate_remote_path("Projects:private")
        with self.assertRaisesRegex(fnsync.FnSyncError, "whitespace"):
            fnsync.validate_url("https://nas.example/\n", False)
        with self.assertRaisesRegex(fnsync.FnSyncError, "query parameters"):
            fnsync.validate_url("https://nas.example/?token=secret", False)
        with self.assertRaisesRegex(fnsync.FnSyncError, "between 30 seconds"):
            fnsync.validate_interval(29)
        with self.assertRaisesRegex(fnsync.FnSyncError, "Invalid bandwidth"):
            fnsync.validate_bwlimit("as-fast-as-possible")
        with self.assertRaisesRegex(fnsync.FnSyncError, "cannot be empty"):
            fnsync.validate_connection_name("  ")
        with self.assertRaisesRegex(fnsync.FnSyncError, "cannot be empty"):
            fnsync.validate_username("\n")

        args = types.SimpleNamespace(password_stdin=True)
        with mock.patch.object(fnsync.sys, "stdin", io.StringIO("\n")):
            with self.assertRaisesRegex(fnsync.FnSyncError, "password cannot be empty"):
                fnsync.password_from_args(args, required=True)
        with mock.patch.object(fnsync.getpass, "getpass", return_value=""):
            with self.assertRaisesRegex(fnsync.FnSyncError, "password cannot be empty"):
                fnsync.password_from_args(types.SimpleNamespace(password_stdin=False), required=True)

    def test_remote_storage_rolls_back_keyring_and_removal_clears_it(self):
        with mock.patch.object(fnsync, "require_rclone", return_value="rclone"), mock.patch.object(
            fnsync, "secret_tool_store", return_value=True
        ), mock.patch.object(
            fnsync, "_write_rclone_config", side_effect=OSError("disk full")
        ), mock.patch.object(fnsync, "secret_tool_clear") as clear:
            with self.assertRaisesRegex(OSError, "disk full"):
                fnsync.store_remote(
                    "fnsync_nas_nas123",
                    "nas123",
                    "Home NAS",
                    "https://nas.example:5006/",
                    "alice",
                    "secret",
                )
        clear.assert_called_once_with("nas123", "connection")

        self.write_remote()
        with mock.patch.object(fnsync, "secret_tool_clear") as clear:
            fnsync.remove_remote(
                "fnsync_nas_nas123",
                "nas123",
                "secret-service",
                "connection",
            )
        self.assertFalse(fnsync._load_rclone_config().has_section("fnsync_nas_nas123"))
        clear.assert_called_once_with("nas123", "connection")

    def test_connection_add_rolls_back_remote_when_store_write_fails(self):
        connection = self.connection()
        args = types.SimpleNamespace(
            name="Home NAS",
            url=connection["url"],
            username="alice",
            password_stdin=True,
            allow_http=False,
            insecure_skip_verify=False,
        )
        with mock.patch.object(fnsync, "password_from_args", return_value="secret"), mock.patch.object(
            fnsync, "verify_unsaved_connection"
        ), mock.patch.object(
            fnsync, "create_connection", return_value=connection
        ), mock.patch.object(
            fnsync, "save_store", side_effect=OSError("disk full")
        ), mock.patch.object(fnsync, "remove_remote") as remove:
            with self.assertRaisesRegex(OSError, "disk full"):
                fnsync.cmd_connection_add(args)
        remove.assert_called_once_with(
            connection["remote_name"],
            connection["secret_id"],
            connection["credential_backend"],
            connection["secret_attribute"],
        )

    def test_empty_and_text_status_commands_remain_actionable(self):
        fnsync.save_store(fnsync.empty_store())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(fnsync.cmd_connection_list(types.SimpleNamespace(json=False)), 0)
            self.assertEqual(fnsync.cmd_task_list(types.SimpleNamespace(json=False)), 0)
            self.assertEqual(fnsync.cmd_sync_now(types.SimpleNamespace(json=False)), 0)
            self.assertEqual(fnsync.print_folder_listing("", [], json_output=False), 0)
        text = output.getvalue()
        self.assertIn("No NAS connections yet", text)
        self.assertIn("No sync tasks yet", text)
        self.assertIn("No enabled sync tasks", text)
        self.assertIn("No subfolders", text)

        task = self.task()
        fnsync.save_store(self.store([task]))
        fnsync.update_status(task["id"], state="ok", message="Complete")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(fnsync.cmd_status(types.SimpleNamespace(json=False)), 0)
        self.assertIn("Task task123: ok Complete", output.getvalue())

    def test_task_command_wrappers_preserve_preview_and_repair_results(self):
        task = self.task(mode="two-way", initialized=False, enabled=False)
        fnsync.save_store(self.store([task]))
        missing_winner = types.SimpleNamespace(task_id=task["id"], winner=None, apply=False, json=True)
        with self.assertRaisesRegex(fnsync.FnSyncError, "requires --winner"):
            fnsync.cmd_task_initialize(missing_winner)

        preview = fnsync.CommandResult(0, "preview complete", ["rclone", "bisync"])
        args = types.SimpleNamespace(task_id=task["id"], winner="local", apply=False, json=True)
        with mock.patch.object(fnsync, "preview_initial", return_value=preview) as run, redirect_stdout(
            io.StringIO()
        ), mock.patch.object(fnsync.sys, "stderr", io.StringIO()):
            self.assertEqual(fnsync.cmd_task_initialize(args), 0)
        run.assert_called_once()

        result = fnsync.CommandResult(0, "ok", ["rclone"])
        with mock.patch.object(fnsync, "test_remote", return_value=result) as remote, redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(
                fnsync.cmd_task_test(types.SimpleNamespace(task_id=task["id"], json=True)),
                0,
            )
        remote.assert_called_once()

        with mock.patch.object(fnsync, "repair_access_markers", return_value=result) as repair, redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(
                fnsync.cmd_task_repair_access(
                    types.SimpleNamespace(task_id=task["id"], resume=True, json=True)
                ),
                0,
            )
        self.assertTrue(repair.call_args.kwargs["resume"])


if __name__ == "__main__":
    unittest.main()
