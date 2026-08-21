import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src" / "fnsync.py"


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fn-sync-cli-")
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.command_log = self.root / "rclone-commands.jsonl"
        self._write_executable(
            "rclone",
            r"""
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            log = os.environ.get("FNSYNC_FAKE_RCLONE_LOG")
            if log:
                with open(log, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(args) + "\n")

            command = args[0] if args else ""
            if command == "version":
                print("rclone v1.70.3")
            elif command == "obscure":
                sys.stdin.read()
                print("obscured-test-password")
            elif command == "lsjson":
                print(json.dumps([
                    {"Name": "Sync", "IsDir": True},
                    {"Name": "readme.txt", "IsDir": False},
                ]))
            elif command == "cat":
                marker_file = os.environ.get("FNSYNC_FAKE_REMOTE_MARKER")
                marker = Path(marker_file).read_text(encoding="utf-8") if marker_file and Path(marker_file).exists() else ""
                print(marker, end="")
            elif command in {"copy", "copyto", "bisync", "lsd"}:
                if command == "copyto" and len(args) > 1:
                    marker_file = os.environ.get("FNSYNC_FAKE_REMOTE_MARKER")
                    if marker_file:
                        Path(marker_file).write_text(Path(args[1]).read_text(encoding="utf-8"), encoding="utf-8")
                if "--dry-run" in args:
                    print("NOTICE: example.txt: Skipped copy as --dry-run is set")
                print("NOTICE: Transferred: 1 / 1, 100%")
            else:
                print(f"unsupported fake rclone command: {command}", file=sys.stderr)
                raise SystemExit(9)
            """,
        )
        self._write_executable(
            "secret-tool",
            """
            #!/bin/sh
            # Force the documented rclone-obscured fallback in the test sandbox.
            exit 1
            """,
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "FNSYNC_LANGUAGE": "en",
                "FNSYNC_RCLONE": str(self.bin_dir / "rclone"),
                "FNSYNC_FAKE_RCLONE_LOG": str(self.command_log),
                "FNSYNC_FAKE_REMOTE_MARKER": str(self.root / "remote-marker"),
                "PATH": f"{self.bin_dir}:{os.environ.get('PATH', '')}",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_executable(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        expected: int = 0,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(extra_env or {})
        command = [sys.executable, str(CONTROLLER), *args]
        if os.environ.get("FNSYNC_COVERAGE_SUBPROCESS") == "1":
            command = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                str(CONTROLLER),
                *args,
            ]
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            env=env,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def test_full_connection_and_two_way_task_lifecycle(self):
        doctor = json.loads(self.run_cli("doctor", "--json").stdout)
        self.assertTrue(doctor["rclone_supported"])
        self.assertEqual(doctor["rclone"], "1.70.3")

        verified = json.loads(
            self.run_cli(
                "connection",
                "verify",
                "--url",
                "https://nas.example:5006/",
                "--username",
                "alice",
                "--password-stdin",
                "--json",
                input_text="correct horse battery staple\n",
            ).stdout
        )
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["folders"][0]["path"], "Sync")

        connection = json.loads(
            self.run_cli(
                "connection",
                "add",
                "--name",
                "Home NAS",
                "--url",
                "https://nas.example:5006/",
                "--username",
                "alice",
                "--password-stdin",
                input_text="correct horse battery staple\n",
            ).stdout
        )
        self.assertEqual(connection["name"], "Home NAS")
        self.assertNotIn("secret_id", connection)
        connection_id = connection["id"]

        listed_connections = json.loads(
            self.run_cli("connection", "list", "--json").stdout
        )
        self.assertEqual([item["id"] for item in listed_connections], [connection_id])
        self.assertTrue(
            json.loads(
                self.run_cli("connection", "test", connection_id, "--json").stdout
            )["ok"]
        )
        folders = json.loads(
            self.run_cli("connection", "folders", connection_id, "--json").stdout
        )
        self.assertEqual(folders["folders"][0]["name"], "Sync")
        renamed = json.loads(
            self.run_cli(
                "connection", "update", connection_id, "--name", "My fnOS"
            ).stdout
        )
        self.assertEqual(renamed["name"], "My fnOS")

        local = self.root / "home" / "Sync" / "Docs"
        task = json.loads(
            self.run_cli(
                "task",
                "add",
                "--name",
                "Documents",
                "--connection",
                connection_id[:6],
                "--local",
                str(local),
                "--remote-path",
                "Sync/Documents",
            ).stdout
        )
        task_id = task["id"]
        self.assertFalse(task["enabled"])
        self.assertFalse(task["initialized"])
        still_used = self.run_cli(
            "connection", "remove", connection_id, expected=2
        )
        self.assertIn("still used by sync tasks", still_used.stderr)

        preview = json.loads(
            self.run_cli(
                "task", "preview", task_id[:6], "--winner", "local", "--json"
            ).stdout
        )
        self.assertTrue(preview["ok"])
        self.assertIn("Skipped copy", preview["output"])

        initialized = json.loads(
            self.run_cli(
                "task",
                "initialize",
                task_id,
                "--winner",
                "local",
                "--apply",
                "--json",
            ).stdout
        )
        self.assertTrue(initialized["ok"])
        marker = (local / "FN_SYNC_ACCESS_TEST").read_text(encoding="utf-8")
        self.assertEqual(
            marker,
            (self.root / "remote-marker").read_text(encoding="utf-8"),
        )

        run = json.loads(
            self.run_cli(
                "task", "run", task_id, "--json"
            ).stdout
        )
        self.assertTrue(run["ok"])

        self.run_cli("task", "disable", task_id)
        self.run_cli("task", "enable", task_id)
        sync = json.loads(
            self.run_cli("sync-now", "--json").stdout
        )
        self.assertTrue(sync["ok"])
        self.assertEqual(sync["count"], 1)

        tasks = json.loads(self.run_cli("task", "list", "--json").stdout)
        self.assertTrue(tasks[0]["enabled"])
        self.assertTrue(tasks[0]["initialized"])
        self.assertNotIn("remote_name", tasks[0])

        status = json.loads(self.run_cli("status", "--json").stdout)
        self.assertEqual(status[0]["status"]["state"], "ok")
        self.assertIn("Transferred", self.run_cli("logs", task_id).stdout)

        self.run_cli("task", "remove", task_id)

        upload_local = self.root / "home" / "Sync" / "Upload"
        upload = json.loads(
            self.run_cli(
                "task",
                "add",
                "--name",
                "Uploads",
                "--mode",
                "upload-only",
                "--connection",
                connection_id,
                "--local",
                str(upload_local),
                "--remote-path",
                "Sync/Uploads",
                "--bwlimit",
                "8M",
                "--filter",
                "- *.tmp",
            ).stdout
        )
        self.assertTrue(upload["initialized"])
        self.assertTrue(
            json.loads(
                self.run_cli("task", "run", upload["id"], "--json").stdout
            )["ok"]
        )
        self.run_cli("task", "remove", upload["id"])
        self.run_cli("connection", "remove", connection_id)
        self.assertEqual(
            json.loads(self.run_cli("connection", "list", "--json").stdout), []
        )

        commands = [
            json.loads(line)
            for line in self.command_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertTrue(any(command and command[0] == "bisync" for command in commands))
        self.assertTrue(any(command and command[0] == "copyto" for command in commands))
        self.assertFalse(
            any("correct horse battery staple" in part for command in commands for part in command)
        )

    def test_invalid_connection_is_rejected_without_persisting_credentials(self):
        failed = self.run_cli(
            "connection",
            "add",
            "--name",
            "Unsafe NAS",
            "--url",
            "http://nas.example:5005/",
            "--username",
            "alice",
            "--password-stdin",
            input_text="secret\n",
            expected=2,
        )
        self.assertIn("Plain HTTP is blocked", failed.stderr)
        self.assertEqual(
            json.loads(self.run_cli("connection", "list", "--json").stdout), []
        )

    def test_cli_reports_unknown_ids_and_version(self):
        self.assertIn("fn-sync 0.", self.run_cli("--version").stdout)
        missing = self.run_cli("task", "run", "missing", expected=2)
        self.assertIn("Task not found", missing.stderr)


if __name__ == "__main__":
    unittest.main()
