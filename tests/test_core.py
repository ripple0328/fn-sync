import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "fnsync.py"
SPEC = importlib.util.spec_from_file_location("fnsync_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
fnsync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fnsync
SPEC.loader.exec_module(fnsync)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fnsync-test-")
        root = Path(self.temp.name)
        self.saved_env = {
            key: os.environ.get(key)
            for key in (
                "XDG_CONFIG_HOME",
                "XDG_STATE_HOME",
                "XDG_DATA_HOME",
                "FNSYNC_LANGUAGE",
                "LC_ALL",
                "LC_MESSAGES",
                "LANGUAGE",
                "LANG",
            )
        }
        os.environ["XDG_CONFIG_HOME"] = str(root / "config")
        os.environ["XDG_STATE_HOME"] = str(root / "state")
        os.environ["XDG_DATA_HOME"] = str(root / "data")
        fnsync.ensure_runtime_dirs()

    def tearDown(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def task(self, mode="two-way"):
        return {
            "id": "abc123",
            "name": "Docs",
            "connection_id": "nas123",
            "mode": mode,
            "local_path": str(Path(self.temp.name) / "local"),
            "remote_name": "fnsync_abc123",
            "remote_path": "Sync/Docs",
            "interval_seconds": 300,
            "filters": [],
        }

    def test_language_defaults_to_system_and_supports_override(self):
        os.environ.pop("FNSYNC_LANGUAGE", None)
        os.environ["LC_ALL"] = "zh_CN.UTF-8"
        self.assertEqual(fnsync.preferred_language(), "zh")
        os.environ["FNSYNC_LANGUAGE"] = "en"
        self.assertEqual(fnsync.preferred_language(), "en")
        os.environ["FNSYNC_LANGUAGE"] = "system"
        os.environ["LC_ALL"] = "en_US.UTF-8"
        self.assertEqual(fnsync.preferred_language(), "en")

    def test_new_running_status_clears_previous_run_fields(self):
        fnsync.update_status(
            "abc123",
            state="error",
            finished_at="yesterday",
            exit_code=7,
            message="old failure",
            dry_run=False,
        )
        fnsync.update_status(
            "abc123",
            state="running",
            action="initial-preview",
            started_at="now",
            message="",
            dry_run=True,
        )
        self.assertEqual(
            fnsync.load_status()["tasks"]["abc123"],
            {
                "state": "running",
                "action": "initial-preview",
                "started_at": "now",
                "message": "",
                "dry_run": True,
            },
        )

    def test_webdav_defaults_use_gentle_concurrency(self):
        args = fnsync.common_rclone_args(self.task())
        self.assertEqual(args[args.index("--checkers") + 1], "2")
        self.assertEqual(args[args.index("--transfers") + 1], "2")
        self.assertEqual(args[args.index("--stats") + 1], "10s")
        self.assertIn("--disable-http2", args)
        self.assertIn("--no-update-dir-modtime", args)

    def test_unauthorized_failure_summary_is_actionable(self):
        summary = fnsync.failure_summary(
            "ERROR : deep/path: couldn't list files: Not Authorized: 401 Unauthorized\n"
            "NOTICE: Failed to bisync with 2 errors: bisync aborted\n"
        )
        self.assertIn("fnOS WebDAV", summary)
        self.assertIn("401 Unauthorized", summary)

    def test_access_marker_failure_summary_preserves_the_real_cause(self):
        summary = fnsync.failure_summary(
            "ERROR : Access test failed: Path1 count 1, Path2 count 0\n"
            "NOTICE: Failed to bisync: bisync aborted\n"
        )
        self.assertIn("access marker", summary)
        self.assertIn("No files were changed", summary)

    def test_large_task_log_rotates_to_one_bounded_previous_file(self):
        path = fnsync.runtime_paths()["logs"] / "abc123.log"
        path.write_text("0123456789abcdef", encoding="utf-8")
        fnsync.rotate_task_log(path, max_bytes=10)
        self.assertFalse(path.exists())
        self.assertEqual(
            path.with_suffix(".log.1").read_text(encoding="utf-8"),
            "6789abcdef",
        )

    def test_planned_change_count_ignores_stats_and_real_actions(self):
        output = (
            "NOTICE: one: Skipped copy as --dry-run is set\n"
            "NOTICE: two: Skipped make directory as --dry-run is set\n"
            "NOTICE: 2 MiB / 2 MiB, 100%\n"
            "INFO: copied a real file\n"
        )
        self.assertEqual(fnsync.planned_change_count(output), 2)

    def test_folder_listing_is_sorted_and_joins_parent_path(self):
        output = '[{"Name":"Zoo","IsDir":true},{"Name":"alpha","IsDir":true},{"Name":"file.txt","IsDir":false}]'
        self.assertEqual(
            fnsync._folder_items(output, "Sync"),
            [
                {"name": "alpha", "path": "Sync/alpha"},
                {"name": "Zoo", "path": "Sync/Zoo"},
            ],
        )

    def test_pre_save_config_is_private_and_removed(self):
        with mock.patch.object(fnsync, "obscure_password", return_value="obscured"):
            with fnsync.temporary_connection_config("https://nas/", "alice", "secret") as path:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                content = path.read_text(encoding="utf-8")
                self.assertIn("pass = obscured", content)
                self.assertNotIn("secret", content)
            self.assertFalse(path.exists())

    def test_connection_add_does_not_save_when_verification_fails(self):
        args = types.SimpleNamespace(
            name="Home NAS",
            url="https://nas/",
            username="alice",
            password_stdin=True,
            allow_http=False,
            insecure_skip_verify=False,
        )
        with mock.patch.object(fnsync, "password_from_args", return_value="secret"), mock.patch.object(
            fnsync, "verify_unsaved_connection", side_effect=fnsync.FnSyncError("not reachable")
        ):
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.cmd_connection_add(args)
        self.assertEqual(fnsync.load_store()["connections"], [])

    def connection(self):
        return {
            "id": "nas123",
            "name": "Home NAS",
            "url": "https://nas/",
            "username": "alice",
            "remote_name": "fnsync_nas_nas123",
            "credential_backend": "rclone-obscured",
            "secret_attribute": "connection",
            "secret_id": "nas123",
            "allow_http": False,
            "insecure_skip_verify": False,
        }

    def store(self, tasks=None):
        return {
            "version": fnsync.CONFIG_VERSION,
            "connections": [self.connection()],
            "tasks": list(tasks or []),
        }

    def test_http_requires_explicit_opt_in(self):
        with self.assertRaises(fnsync.FnSyncError):
            fnsync.validate_url("http://nas.local:5005", False)
        self.assertEqual(
            fnsync.validate_url("http://nas.local:5005", True),
            "http://nas.local:5005/",
        )

    def test_remote_path_rejects_parent_segments(self):
        with self.assertRaises(fnsync.FnSyncError):
            fnsync.validate_remote_path("Sync/../Private")

    def test_overlapping_local_roots_are_rejected(self):
        root = Path(self.temp.name) / "local"
        store = self.store([{**self.task(), "local_path": str(root)}])
        with self.assertRaises(fnsync.FnSyncError):
            fnsync.validate_task_isolation(store, root / "nested", "nas123", "Elsewhere")

    def test_overlapping_remote_roots_are_rejected(self):
        root = Path(self.temp.name) / "other-local"
        store = self.store([self.task()])
        with self.assertRaises(fnsync.FnSyncError):
            fnsync.validate_task_isolation(store, root, "nas123", "Sync")

    def test_bisync_has_safety_and_conflict_guards(self):
        args = fnsync.bisync_args(self.task(), initial="path1")
        self.assertIn("--resync", args)
        self.assertIn("--check-access", args)
        self.assertEqual(
            args[args.index("--check-filename") + 1], fnsync.ACCESS_MARKER
        )
        self.assertEqual(args[args.index("--max-delete") + 1], "50")
        self.assertEqual(args[args.index("--conflict-resolve") + 1], "none")
        self.assertEqual(
            args[args.index("--conflict-suffix") + 1],
            "Omarchy-conflict,NAS-conflict",
        )
        self.assertIn("--backup-dir1", args)
        self.assertIn("--backup-dir2", args)

    def test_one_way_modes_never_use_sync_delete(self):
        upload = fnsync.one_way_args(self.task("upload-only"))
        download = fnsync.one_way_args(self.task("download-only"))
        self.assertEqual(upload[0], "copy")
        self.assertEqual(download[0], "copy")
        self.assertNotIn("sync", upload)
        self.assertNotIn("sync", download)

    def test_public_task_hides_internal_remote_name(self):
        public = fnsync.public_task(
            {**self.task(), "remote_name": "private", "secret_id": "private"}
        )
        self.assertNotIn("remote_name", public)
        self.assertNotIn("secret_id", public)

    def test_secret_service_uses_short_lived_runtime_config(self):
        parser = fnsync._load_rclone_config()
        parser["fnsync_abc123"] = {
            "type": "webdav",
            "url": "https://nas/",
            "vendor": "other",
            "user": "alice",
        }
        fnsync._write_rclone_config(parser)
        task = {**self.task(), "credential_backend": "secret-service"}
        with mock.patch.object(fnsync, "secret_tool_lookup", return_value="pw"), mock.patch.object(
            fnsync, "obscure_password", return_value="obscured"
        ):
            with fnsync.task_rclone_config(task) as path:
                runtime_path = Path(path)
                self.assertNotEqual(runtime_path, fnsync.runtime_paths()["rclone"])
                self.assertEqual(runtime_path.stat().st_mode & 0o777, 0o600)
                self.assertIn("pass = obscured", runtime_path.read_text(encoding="utf-8"))
            self.assertFalse(runtime_path.exists())
        self.assertNotIn(
            "pass =", fnsync.runtime_paths()["rclone"].read_text(encoding="utf-8")
        )

    def test_initialized_two_way_preview_does_not_require_winner(self):
        task = {**self.task(), "initialized": True}
        args = types.SimpleNamespace(task_id=task["id"], winner=None, json=False)
        result = fnsync.CommandResult(0, "preview", ["rclone", "bisync"])
        with mock.patch.object(fnsync, "_task_from_args", return_value=(self.store([task]), task)), mock.patch.object(
            fnsync, "run_task", return_value=result
        ) as run_task:
            self.assertEqual(fnsync.cmd_task_preview(args), 0)
        runtime_task = run_task.call_args.args[0]
        self.assertEqual(runtime_task["connection_name"], "Home NAS")
        self.assertEqual(runtime_task["remote_name"], "fnsync_nas_nas123")
        self.assertTrue(run_task.call_args.kwargs["dry_run"])

    def test_uninitialized_two_way_preview_requires_winner(self):
        task = {**self.task(), "initialized": False}
        args = types.SimpleNamespace(task_id=task["id"], winner=None, json=False)
        with mock.patch.object(fnsync, "_task_from_args", return_value=(self.store([task]), task)):
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.cmd_task_preview(args)

    def test_first_sync_check_records_the_conflict_rule(self):
        task = self.task()
        fnsync.save_store(self.store([task]))
        with mock.patch.object(
            fnsync,
            "run_rclone",
            return_value=fnsync.CommandResult(0, "checked", ["rclone", "bisync"]),
        ) as run_rclone:
            self.assertEqual(fnsync.preview_initial(task, "nas").returncode, 0)
        self.assertEqual(run_rclone.call_args.kwargs["status_action"], "initial-preview")
        self.assertTrue(run_rclone.call_args.kwargs["dry_run"])
        self.assertEqual(
            run_rclone.call_args.kwargs["status_details"],
            {"conflict_winner": "nas"},
        )
        self.assertEqual(
            fnsync.load_store()["tasks"][0]["first_sync_check"]["conflict_winner"],
            "nas",
        )

    def test_first_sync_requires_a_matching_successful_check(self):
        task = self.task()
        task["first_sync_check"] = {"conflict_winner": "local"}
        with mock.patch.object(fnsync, "ensure_access_markers") as ensure_access:
            with self.assertRaises(fnsync.FnSyncError):
                fnsync.initialize_task(task, "nas")
        ensure_access.assert_not_called()

    def test_successful_first_sync_enables_automatic_sync(self):
        task = {
            **self.task(),
            "initialized": False,
            "enabled": False,
            "first_sync_check": {"conflict_winner": "local"},
        }
        fnsync.save_store(self.store([task]))
        result = fnsync.CommandResult(0, "complete", ["rclone", "bisync"])
        with mock.patch.object(fnsync, "ensure_access_markers"), mock.patch.object(
            fnsync, "run_rclone", return_value=result
        ) as run_rclone:
            self.assertEqual(fnsync.initialize_task(task, "local").returncode, 0)
        saved = fnsync.load_store()["tasks"][0]
        self.assertTrue(saved["initialized"])
        self.assertTrue(saved["enabled"])
        self.assertNotIn("first_sync_check", saved)
        self.assertEqual(
            run_rclone.call_args.kwargs["status_details"],
            {"conflict_winner": "local"},
        )

    def test_missing_nas_marker_pauses_before_bisync(self):
        task = {**self.task(), "initialized": True, "enabled": True}
        local = Path(task["local_path"])
        local.mkdir(parents=True)
        (local / fnsync.ACCESS_MARKER).write_text(
            fnsync.access_marker_text(task), encoding="utf-8"
        )
        fnsync.save_store(self.store([task]))
        missing = fnsync.subprocess.CompletedProcess(
            ["rclone", "cat"], 3, "", "Failed to cat: object not found"
        )
        with mock.patch.object(fnsync, "_remote_marker_read", return_value=missing), mock.patch.object(
            fnsync, "run_rclone"
        ) as run_rclone:
            with self.assertRaises(fnsync.AccessMarkerError):
                fnsync.run_task(fnsync.hydrate_task(self.store([task]), task))
        run_rclone.assert_not_called()
        saved = fnsync.load_store()["tasks"][0]
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["safety_issue"]["code"], "access-marker")
        status = fnsync.load_status()["tasks"][task["id"]]
        self.assertEqual(status["error_code"], "access-marker")
        self.assertEqual(status["action"], "safety-check")

    def test_marker_disappearing_during_bisync_also_pauses_task(self):
        task = {**self.task(), "initialized": True, "enabled": True}
        Path(task["local_path"]).mkdir(parents=True)
        fnsync.save_store(self.store([task]))
        failed = fnsync.CommandResult(
            7,
            "ERROR : Access test failed: Path1 count 1, Path2 count 0\n"
            "NOTICE: Failed to bisync: bisync aborted\n",
            ["rclone", "bisync"],
        )
        with mock.patch.object(fnsync, "preflight_access_markers"), mock.patch.object(
            fnsync, "run_rclone", return_value=failed
        ):
            self.assertEqual(fnsync.run_task(task).returncode, 7)
        saved = fnsync.load_store()["tasks"][0]
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["safety_issue"]["code"], "access-marker")
        self.assertEqual(
            fnsync.load_status()["tasks"][task["id"]]["error_code"],
            "access-marker",
        )

    def test_repair_marker_can_verify_and_resume_task(self):
        task = {
            **self.task(),
            "initialized": True,
            "enabled": False,
            "safety_issue": {"code": "access-marker"},
        }
        local = Path(task["local_path"])
        local.mkdir(parents=True)
        (local / fnsync.LEGACY_ACCESS_MARKER).write_text("old", encoding="utf-8")
        fnsync.save_store(self.store([task]))
        setup = fnsync.CommandResult(0, "", ["rclone", "copyto"])
        with mock.patch.object(fnsync, "ensure_access_markers", return_value=setup):
            result = fnsync.repair_access_markers(task, resume=True)
        self.assertEqual(result.returncode, 0)
        saved = fnsync.load_store()["tasks"][0]
        self.assertTrue(saved["enabled"])
        self.assertNotIn("safety_issue", saved)
        self.assertFalse((local / fnsync.LEGACY_ACCESS_MARKER).exists())
        status = fnsync.load_status()["tasks"][task["id"]]
        self.assertEqual(status["action"], "repair-access")
        self.assertEqual(status["state"], "ok")

    def test_two_tasks_share_one_connection_without_copying_credentials(self):
        first = self.task()
        second = {
            **self.task("upload-only"),
            "id": "def456",
            "name": "Photos",
            "local_path": str(Path(self.temp.name) / "photos"),
            "remote_path": "Sync/Photos",
        }
        store = self.store([first, second])
        one = fnsync.hydrate_task(store, first)
        two = fnsync.hydrate_task(store, second)
        self.assertEqual(one["remote_name"], two["remote_name"])
        self.assertEqual(one["secret_id"], two["secret_id"])
        self.assertNotIn("password", first)
        self.assertNotIn("password", second)

    def test_unused_connection_can_be_removed_without_touching_files(self):
        fnsync.save_store(self.store())
        args = types.SimpleNamespace(connection_id="nas123")
        with mock.patch.object(fnsync, "remove_remote") as remove_remote:
            self.assertEqual(fnsync.cmd_connection_remove(args), 0)
        self.assertEqual(fnsync.load_store()["connections"], [])
        remove_remote.assert_called_once_with(
            "fnsync_nas_nas123",
            "nas123",
            "rclone-obscured",
            "connection",
        )

    def test_v1_migration_keeps_legacy_secret_lookup_and_separates_connection(self):
        parser = fnsync._load_rclone_config()
        parser["fnsync_abc123"] = {
            "type": "webdav",
            "url": "https://nas/",
            "vendor": "other",
            "user": "alice",
        }
        fnsync._write_rclone_config(parser)
        legacy_task = {
            **self.task(),
            "remote_name": "fnsync_abc123",
            "remote_url": "https://nas/",
            "credential_backend": "secret-service",
        }
        legacy_task.pop("connection_id")
        migrated = fnsync.migrate_v1_store({"version": 1, "tasks": [legacy_task]})
        connection = migrated["connections"][0]
        task = migrated["tasks"][0]
        self.assertEqual(migrated["version"], 2)
        self.assertEqual(task["connection_id"], connection["id"])
        self.assertEqual(connection["secret_attribute"], "task")
        self.assertEqual(connection["secret_id"], "abc123")
        self.assertNotIn("credential_backend", task)


if __name__ == "__main__":
    unittest.main()
