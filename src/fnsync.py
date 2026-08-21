#!/usr/bin/env python3
"""fn-sync Linux controller for fnOS.

The controller deliberately uses fnOS' documented WebDAV service through
rclone.  It does not depend on the private protocol used by the official
Windows/macOS sync client.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import datetime as dt
import fcntl
import getpass
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APP_NAME = "fnsync"
APP_VERSION = "0.8.2"
CONFIG_VERSION = 2
MIN_RCLONE_VERSION = (1, 66, 0)
MODES = ("two-way", "upload-only", "download-only")
ACCESS_MARKER = "FN_SYNC_ACCESS_TEST"
LEGACY_ACCESS_MARKER = ".fnsync-access"
MAX_TASK_LOG_BYTES = 5 * 1024 * 1024
DEFAULT_FILTERS = (
    "- .fnsync-versions/**",
    "- **/.fnsync-versions/**",
    "- **/.DS_Store",
    "- **/Thumbs.db",
    "- **/*.tmp",
    "- **/*.temp",
    "- **/*.part",
    "- **/~$*",
)


def preferred_language() -> str:
    override = os.environ.get("FNSYNC_LANGUAGE", "system").lower()
    if override in {"en", "zh"}:
        return override
    locale_name = next(
        (
            os.environ[name]
            for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")
            if os.environ.get(name)
        ),
        "en",
    ).lower()
    return "zh" if re.match(r"^zh([_.-]|$)", locale_name) else "en"


def tr(english: str, chinese: str) -> str:
    return chinese if preferred_language() == "zh" else english


class FnSyncError(RuntimeError):
    """An expected, user-facing failure."""


class TaskBusyError(FnSyncError):
    """A sync task already has another process holding its lock."""


class AccessMarkerError(FnSyncError):
    """A two-way task's access marker is missing or no longer trustworthy."""

    error_code = "access-marker"


def _xdg_path(env_name: str, fallback: Path, suffix: str) -> Path:
    override = os.environ.get(env_name)
    base = Path(override).expanduser() if override else fallback
    return base / suffix


def config_dir() -> Path:
    return _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config", APP_NAME)


def state_dir() -> Path:
    return _xdg_path(
        "XDG_STATE_HOME", Path.home() / ".local" / "state", APP_NAME
    )


def data_dir() -> Path:
    return _xdg_path(
        "XDG_DATA_HOME", Path.home() / ".local" / "share", APP_NAME
    )


def runtime_paths() -> dict[str, Path]:
    cfg = config_dir()
    state = state_dir()
    return {
        "config_dir": cfg,
        "tasks": cfg / "tasks.json",
        "rclone": cfg / "rclone.conf",
        "state_dir": state,
        "status": state / "status.json",
        "filters": state / "filters",
        "logs": state / "logs",
        "locks": state / "locks",
        "work": state / "work",
        "backups": state / "versions",
    }


def ensure_runtime_dirs() -> None:
    paths = runtime_paths()
    for key in ("config_dir", "state_dir", "filters", "logs", "locks", "work", "backups"):
        paths[key].mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(PermissionError):
            paths[key].chmod(0o700)


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def atomic_json_write(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise FnSyncError(tr(f"Could not read {path}: {exc}", f"无法读取 {path}: {exc}")) from exc


def empty_store() -> dict[str, Any]:
    return {"version": CONFIG_VERSION, "connections": [], "tasks": []}


def migrate_v1_store(store: dict[str, Any]) -> dict[str, Any]:
    """Move per-task WebDAV remotes into reusable NAS connections.

    Each legacy task gets its own connection so migration never assumes that
    two tasks used the same password.  The existing rclone section and Secret
    Service lookup key remain valid, so no credential is copied into JSON.
    """
    if store.get("version") != 1 or not isinstance(store.get("tasks"), list):
        raise FnSyncError(tr("The task configuration version is not supported", "任务配置版本不受支持"))
    parser = _load_rclone_config()
    migrated = empty_store()
    for original in store["tasks"]:
        task = dict(original)
        task_id = str(task.get("id") or "")
        remote_name = str(task.get("remote_name") or "")
        section = parser[remote_name] if remote_name and parser.has_section(remote_name) else {}
        url = str(task.get("remote_url") or section.get("url") or "")
        username = str(section.get("user") or "")
        connection_id = f"nas-{task_id}"
        host = urlsplit(url).hostname or "fnOS NAS"
        connection = {
            "id": connection_id,
            "name": host,
            "url": url,
            "username": username,
            "remote_name": remote_name,
            "credential_backend": task.get("credential_backend", "rclone-obscured"),
            "secret_attribute": "task",
            "secret_id": task_id,
            "allow_http": bool(task.get("allow_http")),
            "insecure_skip_verify": bool(task.get("insecure_skip_verify")),
            "created_at": task.get("created_at", now_iso()),
            "updated_at": now_iso(),
        }
        for key in (
            "remote_name",
            "remote_url",
            "credential_backend",
            "allow_http",
            "insecure_skip_verify",
        ):
            task.pop(key, None)
        task["connection_id"] = connection_id
        task["updated_at"] = now_iso()
        migrated["connections"].append(connection)
        migrated["tasks"].append(task)
    return migrated


def load_store() -> dict[str, Any]:
    path = runtime_paths()["tasks"]
    store = load_json(path, empty_store())
    if store.get("version") == 1:
        migrated = migrate_v1_store(store)
        backup = path.with_name("tasks.v1.backup.json")
        if not backup.exists():
            atomic_json_write(backup, store)
        atomic_json_write(path, migrated)
        store = migrated
    if (
        store.get("version") != CONFIG_VERSION
        or not isinstance(store.get("connections"), list)
        or not isinstance(store.get("tasks"), list)
    ):
        raise FnSyncError(tr("The task configuration version is not supported", "任务配置版本不受支持"))
    return store


def save_store(store: dict[str, Any]) -> None:
    atomic_json_write(runtime_paths()["tasks"], store)


def load_status() -> dict[str, Any]:
    status = load_json(runtime_paths()["status"], {"tasks": {}})
    if not isinstance(status.get("tasks"), dict):
        return {"tasks": {}}
    return status


def update_status(task_id: str, **values: Any) -> None:
    ensure_runtime_dirs()
    lock_path = runtime_paths()["locks"] / "status.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            status = load_status()
            if values.get("state") == "running":
                # A new run must not inherit the previous run's exit code,
                # completion time, dry-run flag, or failure message.
                status["tasks"][task_id] = dict(values)
            else:
                current = status["tasks"].setdefault(task_id, {})
                current.update(values)
            atomic_json_write(runtime_paths()["status"], status)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def find_task(store: dict[str, Any], task_id: str) -> dict[str, Any]:
    exact = [task for task in store["tasks"] if task["id"] == task_id]
    if exact:
        return exact[0]
    prefix = [task for task in store["tasks"] if task["id"].startswith(task_id)]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        raise FnSyncError(tr(f"Task ID prefix is not unique: {task_id}", f"任务 ID 前缀不唯一: {task_id}"))
    raise FnSyncError(tr(f"Task not found: {task_id}", f"找不到任务: {task_id}"))


def find_connection(store: dict[str, Any], connection_id: str) -> dict[str, Any]:
    exact = [item for item in store["connections"] if item["id"] == connection_id]
    if exact:
        return exact[0]
    prefix = [item for item in store["connections"] if item["id"].startswith(connection_id)]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        raise FnSyncError(tr(f"NAS connection ID prefix is not unique: {connection_id}", f"NAS 连接 ID 前缀不唯一: {connection_id}"))
    raise FnSyncError(tr(f"NAS connection not found: {connection_id}", f"找不到 NAS 连接: {connection_id}"))


def public_connection(connection: dict[str, Any]) -> dict[str, Any]:
    hidden = {"remote_name", "credential_backend", "secret_attribute", "secret_id"}
    return {key: value for key, value in connection.items() if key not in hidden}


def hydrate_task(store: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    connection = find_connection(store, str(task.get("connection_id") or ""))
    hydrated = dict(task)
    hydrated.update(
        {
            "connection_name": connection["name"],
            "connection_username": connection["username"],
            "remote_url": connection["url"],
            "remote_name": connection["remote_name"],
            "credential_backend": connection["credential_backend"],
            "secret_attribute": connection.get("secret_attribute", "connection"),
            "secret_id": connection.get("secret_id", connection["id"]),
            "allow_http": bool(connection.get("allow_http")),
            "insecure_skip_verify": bool(connection.get("insecure_skip_verify")),
        }
    )
    return hydrated


def validate_local_path(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    home = Path.home().resolve()
    forbidden = {Path("/"), home}
    if path in forbidden:
        raise FnSyncError(tr("For safety, / and the entire home directory cannot be used as a sync folder", "为避免误操作，不能把 / 或整个主目录设为同步目录"))
    if not path.is_absolute():
        raise FnSyncError(tr("The local sync folder must be an absolute path", "本地同步目录必须是绝对路径"))
    try:
        path.relative_to(home)
    except ValueError:
        # Non-home paths are allowed, but never broad system directories.
        if len(path.parts) < 3:
            raise FnSyncError(tr("The local sync folder is too broad", "本地同步目录范围过大"))
    return path


def validate_remote_path(raw: str) -> str:
    path = raw.strip().strip("/")
    if not path:
        raise FnSyncError(tr("The remote folder cannot be empty; choose a dedicated subfolder for this sync task", "远端目录不能为空；请为同步任务选择一个专用子目录"))
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise FnSyncError(tr("The remote folder contains an invalid path segment", "远端目录包含非法路径片段"))
    if any(char in path for char in ("\n", "\r", ":")):
        raise FnSyncError(tr("The remote folder contains invalid characters", "远端目录包含非法字符"))
    return path


def validate_url(raw: str, allow_http: bool) -> str:
    if any(char.isspace() or ord(char) < 32 for char in raw):
        raise FnSyncError(tr("The WebDAV address cannot contain whitespace or control characters", "WebDAV 地址不能包含空白或控制字符"))
    value = raw.strip().rstrip("/") + "/"
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise FnSyncError(tr("The WebDAV address must be a complete http(s) URL", "WebDAV 地址必须是完整的 http(s) URL"))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise FnSyncError(tr("The WebDAV address cannot contain credentials, query parameters, or fragments", "WebDAV 地址不能包含凭据、查询参数或片段"))
    if parsed.scheme == "http" and not allow_http:
        raise FnSyncError(tr("Plain HTTP is blocked by default; explicitly allow it only for trusted-LAN testing", "默认拒绝明文 HTTP；仅可信局域网测试可显式允许"))
    return value


def validate_interval(value: int) -> int:
    if value < 30 or value > 86400:
        raise FnSyncError(tr("The sync interval must be between 30 seconds and 24 hours", "同步间隔必须在 30 秒到 24 小时之间"))
    return value


def validate_bwlimit(value: str | None) -> str | None:
    if not value:
        return None
    if not re.fullmatch(r"(?i)(off|\d+(?:\.\d+)?[kmg]?i?b?)", value.strip()):
        raise FnSyncError(tr("Invalid bandwidth limit; use a value such as 8M, 500KiB, or off", "限速格式无效，例如 8M、500KiB 或 off"))
    return value.strip()


def paths_overlap(first: Path, second: Path) -> bool:
    """Return whether either resolved path contains the other."""
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def validate_task_isolation(
    store: dict[str, Any], local: Path, connection_id: str, remote_path: str
) -> None:
    connection = find_connection(store, connection_id)
    for task in store["tasks"]:
        existing_local = Path(task["local_path"]).expanduser().resolve()
        if paths_overlap(local, existing_local):
            raise FnSyncError(
                tr(
                    f"The local folder overlaps task {task['name']}; use a separate folder for each task",
                    f"本地目录与已有任务 {task['name']} 重叠；请为每个任务使用不重叠的目录",
                )
            )
        existing_connection = find_connection(store, str(task.get("connection_id") or ""))
        if existing_connection.get("url") != connection.get("url"):
            continue
        existing_remote = task["remote_path"].strip("/")
        if (
            remote_path == existing_remote
            or remote_path.startswith(existing_remote + "/")
            or existing_remote.startswith(remote_path + "/")
        ):
            raise FnSyncError(
                tr(
                    f"The NAS folder overlaps task {task['name']}; use a separate remote folder for each task",
                    f"NAS 目录与已有任务 {task['name']} 重叠；请为每个任务使用不重叠的远端目录",
                )
            )


def rclone_binary() -> str:
    candidate = os.environ.get("FNSYNC_RCLONE") or shutil.which("rclone")
    if not candidate:
        raise FnSyncError(tr("rclone was not found; install rclone 1.66 or newer", "未找到 rclone；请先安装 rclone 1.66 或更新版本"))
    return candidate


def rclone_version(binary: str | None = None) -> tuple[int, int, int]:
    binary = binary or rclone_binary()
    try:
        result = subprocess.run(
            [binary, "version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FnSyncError(tr(f"Could not run rclone: {exc}", f"无法执行 rclone: {exc}")) from exc
    match = re.search(r"rclone v(\d+)\.(\d+)(?:\.(\d+))?", result.stdout + result.stderr)
    if result.returncode or not match:
        raise FnSyncError(tr("Could not determine the rclone version", "无法识别 rclone 版本"))
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def require_rclone() -> str:
    binary = rclone_binary()
    version = rclone_version(binary)
    if version < MIN_RCLONE_VERSION:
        found = ".".join(map(str, version))
        wanted = ".".join(map(str, MIN_RCLONE_VERSION))
        raise FnSyncError(tr(f"rclone {found} is too old; version {wanted} or newer is required", f"rclone {found} 太旧，需要 {wanted} 或更新版本"))
    return binary


def _write_rclone_config(parser: configparser.ConfigParser) -> None:
    path = runtime_paths()["rclone"]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".rclone.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _load_rclone_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[method-assign]
    path = runtime_paths()["rclone"]
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def obscure_password(password: str) -> str:
    binary = require_rclone()
    try:
        result = subprocess.run(
            [binary, "obscure", "-"],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FnSyncError(tr(f"Could not protect the WebDAV password: {exc}", f"无法保护 WebDAV 密码: {exc}")) from exc
    if result.returncode or not result.stdout.strip():
        raise FnSyncError(tr("rclone could not protect the WebDAV password", "rclone 无法保护 WebDAV 密码"))
    return result.stdout.strip()


def secret_tool_store(
    secret_id: str, label: str, password: str, attribute: str = "connection"
) -> bool:
    if os.environ.get("FNSYNC_DISABLE_SECRET_SERVICE") == "1":
        return False
    binary = shutil.which("secret-tool")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "store", "--label", label, "application", APP_NAME, attribute, secret_id],
            input=password,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def secret_tool_lookup(secret_id: str, attribute: str = "connection") -> str:
    binary = shutil.which("secret-tool")
    if not binary:
        raise FnSyncError(tr("The task password is in the desktop keyring, but secret-tool was not found", "任务密码保存在桌面密钥环，但未找到 secret-tool"))
    try:
        result = subprocess.run(
            [binary, "lookup", "application", APP_NAME, attribute, secret_id],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FnSyncError(tr(f"Could not read the desktop keyring: {exc}", f"无法读取桌面密钥环: {exc}")) from exc
    password = result.stdout.rstrip("\r\n")
    if result.returncode or not password:
        raise FnSyncError(tr("Could not read this task's WebDAV password from the desktop keyring", "无法从桌面密钥环读取该任务的 WebDAV 密码"))
    return password


def secret_tool_clear(secret_id: str, attribute: str = "connection") -> None:
    binary = shutil.which("secret-tool")
    if not binary:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            [binary, "clear", "application", APP_NAME, attribute, secret_id],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )


def store_remote(
    remote_name: str,
    secret_id: str,
    connection_label: str,
    url: str,
    username: str,
    password: str,
    secret_attribute: str = "connection",
) -> str:
    require_rclone()
    credential_backend = "secret-service" if secret_tool_store(
        secret_id, f"FN sync NAS: {connection_label}", password, secret_attribute
    ) else "rclone-obscured"
    parser = _load_rclone_config()
    remote = {
        "type": "webdav",
        "url": url,
        "vendor": "other",
        "user": username,
    }
    if credential_backend == "rclone-obscured":
        remote["pass"] = obscure_password(password)
    parser[remote_name] = remote
    try:
        _write_rclone_config(parser)
    except Exception:
        if credential_backend == "secret-service":
            secret_tool_clear(secret_id, secret_attribute)
        raise
    return credential_backend


def remove_remote(
    remote_name: str,
    secret_id: str,
    credential_backend: str,
    secret_attribute: str = "connection",
) -> None:
    parser = _load_rclone_config()
    if parser.remove_section(remote_name):
        _write_rclone_config(parser)
    if credential_backend == "secret-service":
        secret_tool_clear(secret_id, secret_attribute)


@contextlib.contextmanager
def task_rclone_config(task: dict[str, Any]) -> Iterator[Path]:
    base = runtime_paths()["rclone"]
    if task.get("credential_backend") != "secret-service":
        yield base
        return

    parser = _load_rclone_config()
    remote_name = task["remote_name"]
    if not parser.has_section(remote_name):
        raise FnSyncError(tr("The task's rclone remote configuration does not exist", "任务的 rclone 远端配置不存在"))
    parser[remote_name]["pass"] = obscure_password(
        secret_tool_lookup(
            str(task.get("secret_id") or task.get("connection_id") or task["id"]),
            str(task.get("secret_attribute") or "connection"),
        )
    )
    fd, tmp_name = tempfile.mkstemp(prefix=".runtime-rclone.", dir=runtime_paths()["state_dir"])
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        yield tmp
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


@contextlib.contextmanager
def temporary_connection_config(url: str, username: str, password: str) -> Iterator[Path]:
    """Create a short-lived config for pre-save verification without persisting credentials."""
    ensure_runtime_dirs()
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[method-assign]
    parser["fnsync_verify"] = {
        "type": "webdav",
        "url": url,
        "vendor": "other",
        "user": username,
        "pass": obscure_password(password),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".verify-rclone.", dir=runtime_paths()["state_dir"])
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        yield tmp
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def filter_file(task: dict[str, Any]) -> Path:
    path = runtime_paths()["filters"] / f"{task['id']}.rules"
    rules = list(DEFAULT_FILTERS)
    rules.extend(task.get("filters", []))
    content = "\n".join(rules) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    return path


def remote_spec(task: dict[str, Any], suffix: str = "") -> str:
    path = task["remote_path"]
    if suffix:
        path = f"{path.rstrip('/')}/{suffix.lstrip('/')}"
    return f"{task['remote_name']}:{path}"


def common_rclone_args(task: dict[str, Any]) -> list[str]:
    args = [
        "--config",
        str(runtime_paths()["rclone"]),
        "--filter-from",
        str(filter_file(task)),
        "--transfers",
        "2",
        "--checkers",
        "2",
        "--retries",
        "3",
        "--retries-sleep",
        "2s",
        "--low-level-retries",
        "10",
        "--contimeout",
        "15s",
        "--timeout",
        "5m",
        # fnOS WebDAV can intermittently return 401 on concurrent HTTP/2
        # streams even though the same paths work over separate requests.
        # Keep HTTPS, but use the more conservative HTTP/1.1 transport.
        "--disable-http2",
        # Directory timestamps are not part of fn-sync's reconciliation model.
        # Avoid a very long WebDAV metadata tail after file comparison.
        "--no-update-dir-modtime",
        "--stats",
        "10s",
        "--stats-one-line",
    ]
    if task.get("bwlimit") and task["bwlimit"].lower() != "off":
        args += ["--bwlimit", task["bwlimit"]]
    if task.get("insecure_skip_verify"):
        args.append("--no-check-certificate")
    return args


def bisync_args(task: dict[str, Any], *, initial: str | None = None) -> list[str]:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    local_backup = runtime_paths()["backups"] / task["id"] / stamp
    remote_backup = remote_spec(task, f".fnsync-versions/{task['id']}/{stamp}")
    args = [
        "bisync",
        task["local_path"],
        remote_spec(task),
        "--workdir",
        str(runtime_paths()["work"] / task["id"]),
        "--check-access",
        "--check-filename",
        ACCESS_MARKER,
        "--max-delete",
        "50",
        "--resilient",
        "--recover",
        "--max-lock",
        "2m",
        "--conflict-resolve",
        "none",
        "--conflict-loser",
        "num",
        "--conflict-suffix",
        "Omarchy-conflict,NAS-conflict",
        "--suffix-keep-extension",
        "--create-empty-src-dirs",
        "--backup-dir1",
        str(local_backup),
        "--backup-dir2",
        remote_backup,
    ]
    if initial:
        args += ["--resync", "--resync-mode", initial]
    args += common_rclone_args(task)
    return args


def one_way_args(task: dict[str, Any]) -> list[str]:
    local = task["local_path"]
    remote = remote_spec(task)
    if task["mode"] == "upload-only":
        source, destination = local, remote
    else:
        source, destination = remote, local
    return ["copy", source, destination, "--create-empty-src-dirs"] + common_rclone_args(task)


@dataclass
class CommandResult:
    returncode: int
    output: str
    command: list[str]
    streamed: bool = False


def sanitize_output(output: str) -> str:
    # rclone should not print secrets, but redact URL userinfo defensively.
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    return re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1***@", output)


def failure_summary(output: str) -> str:
    if "Access test failed" in output or "check file check failed" in output:
        return tr(
            "Safety check stopped this task because its FN sync access marker is missing or changed. No files were changed. Confirm both task folders, then repair the safety check.",
            "安全检查已停止此任务，因为飞牛同步访问标记缺失或已更改。未修改任何文件。请确认任务两端文件夹无误，然后修复安全检查。",
        )
    if "401 Unauthorized" in output:
        return tr(
            "fnOS WebDAV rejected one or more folder reads (401 Unauthorized). Retry after a moment; if it repeats, verify this account can read the whole task folder.",
            "fnOS WebDAV 拒绝了一个或多个文件夹读取请求（401 Unauthorized）。请稍后重试；若问题持续，请确认此账号可读取整个任务文件夹。",
        )
    return last_meaningful_line(output)


def is_access_marker_failure(output: str) -> bool:
    return "Access test failed" in output or "check file check failed" in output


def planned_change_count(output: str) -> int:
    return sum(
        1
        for line in output.splitlines()
        if "Skipped " in line and "--dry-run is set" in line
    )


def run_streaming(command: list[str], timeout: int) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run an interactive CLI action while forwarding sanitized progress."""
    started = time.monotonic()
    chunks: list[str] = []
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    stream: queue.Queue[str | None] = queue.Queue()

    def read_stream() -> None:
        try:
            for line in process.stdout:
                stream.put(line)
        finally:
            stream.put(None)

    reader = threading.Thread(target=read_stream, name="fn-sync-output", daemon=True)
    reader.start()

    def interrupt_stream(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt_stream)
    timed_out = False

    def forward(line: str) -> None:
        clean = sanitize_output(line)
        chunks.append(clean)
        # Let ordinary per-file dry-run lines use normal pipe buffering.
        # Flush stats and failures immediately so the panel stays live
        # without forcing one system call for every planned file.
        flush_progress = bool(
            "ERROR :" in clean
            or "Failed to" in clean
            or re.search(r"NOTICE:.*\s/\s.*%", clean)
        )
        print(clean, end="", flush=flush_progress)

    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0 and process.poll() is None:
                timed_out = True
                process.terminate()
                break
            try:
                line = stream.get(timeout=max(0.01, min(0.2, max(0.0, remaining))))
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                break
            forward(line)
        if timed_out:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        reader.join(timeout=1)
        while True:
            try:
                remaining_line = stream.get_nowait()
            except queue.Empty:
                break
            if remaining_line is not None:
                forward(remaining_line)
        process.stdout.close()
        signal.signal(signal.SIGTERM, previous_sigterm)
    output = "".join(chunks)
    if timed_out:
        timeout_message = tr(
            "The task timed out and this run was stopped.",
            "任务超时，已停止本次运行。",
        )
        output += "\n" + timeout_message + "\n"
        print(timeout_message, flush=True)
        return subprocess.CompletedProcess(command, 124, output, timeout_message), output
    return subprocess.CompletedProcess(command, process.returncode, output, ""), output


def normalize_browse_path(raw: str) -> str:
    value = raw.strip().strip("/")
    return validate_remote_path(value) if value else ""


def _folder_items(output: str, parent: str) -> list[dict[str, str]]:
    try:
        raw_items = json.loads(output or "[]")
    except json.JSONDecodeError as exc:
        raise FnSyncError(tr("The NAS returned an invalid folder listing", "NAS 返回了无效的文件夹列表")) from exc
    if not isinstance(raw_items, list):
        raise FnSyncError(tr("The NAS returned an invalid folder listing", "NAS 返回了无效的文件夹列表"))
    folders: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict) or not item.get("IsDir"):
            continue
        name = str(item.get("Name") or "").strip("/")
        if not name or name in {".", ".."} or "/" in name:
            continue
        path = f"{parent}/{name}" if parent else name
        folders.append({"name": name, "path": path})
    return sorted(folders, key=lambda item: item["name"].casefold())


def _run_folder_listing(
    remote_name: str,
    path: str,
    config_path: Path,
    *,
    insecure_skip_verify: bool,
) -> list[dict[str, str]]:
    binary = require_rclone()
    remote = f"{remote_name}:{path}" if path else f"{remote_name}:"
    command = [
        binary,
        "lsjson",
        remote,
        "--dirs-only",
        "--max-depth",
        "1",
        "--no-modtime",
        "--no-mimetype",
        "--config",
        str(config_path),
    ]
    if insecure_skip_verify:
        command.append("--no-check-certificate")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FnSyncError(tr(f"Could not browse NAS folders: {exc}", f"无法浏览 NAS 文件夹: {exc}")) from exc
    output = sanitize_output((result.stdout or "") + (result.stderr or ""))
    if result.returncode:
        raise FnSyncError(last_meaningful_line(output))
    return _folder_items(result.stdout or "[]", path)


def browse_saved_connection(connection: dict[str, Any], raw_path: str = "") -> list[dict[str, str]]:
    path = normalize_browse_path(raw_path)
    task = connection_runtime_task(connection)
    with task_rclone_config(task) as config_path:
        return _run_folder_listing(
            connection["remote_name"],
            path,
            config_path,
            insecure_skip_verify=bool(connection.get("insecure_skip_verify")),
        )


def verify_unsaved_connection(
    url: str,
    username: str,
    password: str,
    *,
    allow_http: bool,
    insecure_skip_verify: bool,
    raw_path: str = "",
) -> list[dict[str, str]]:
    checked_url = validate_url(url, allow_http)
    checked_username = validate_username(username)
    path = normalize_browse_path(raw_path)
    with temporary_connection_config(checked_url, checked_username, password) as config_path:
        return _run_folder_listing(
            "fnsync_verify",
            path,
            config_path,
            insecure_skip_verify=insecure_skip_verify,
        )


@contextlib.contextmanager
def task_lock(task_id: str) -> Iterator[None]:
    ensure_runtime_dirs()
    path = runtime_paths()["locks"] / f"{task_id}.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TaskBusyError(tr("This task is already running", "该任务正在运行")) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_rclone(
    task: dict[str, Any],
    args: Sequence[str],
    *,
    dry_run: bool = False,
    status_action: str = "sync",
    status_details: dict[str, Any] | None = None,
) -> CommandResult:
    binary = require_rclone()
    ensure_runtime_dirs()
    log_path = runtime_paths()["logs"] / f"{task['id']}.log"
    command = [binary, *args]
    with task_lock(task["id"]):
        started = now_iso()
        details = dict(status_details or {})
        update_status(
            task["id"],
            state="running",
            action=status_action,
            started_at=started,
            message="",
            dry_run=dry_run,
            **details,
        )
        try:
            with task_rclone_config(task) as effective_config:
                command = [
                    binary,
                    *(
                        str(effective_config) if item == str(runtime_paths()["rclone"]) else item
                        for item in args
                    ),
                ]
                if dry_run:
                    command.append("--dry-run")
                command_timeout = max(900, int(task.get("interval_seconds", 300)) * 4)
                streamed = os.environ.get("FNSYNC_STREAM_OUTPUT") == "1"
                if streamed:
                    result, output = run_streaming(command, command_timeout)
                else:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=command_timeout,
                        check=False,
                    )
                    output = sanitize_output((result.stdout or "") + (result.stderr or ""))
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            output = sanitize_output(stdout + stderr)
            timeout_message = tr("The task timed out", "任务超时")
            result = subprocess.CompletedProcess(command, 124, output, timeout_message)
            output += "\n" + tr("The task timed out and this run was stopped.", "任务超时，已停止本次运行。") + "\n"
        except KeyboardInterrupt:
            output = tr(
                "First-sync check stopped by the user; no files were changed.",
                "用户已停止首次同步检查；未修改任何文件。",
            ) + "\n"
            result = subprocess.CompletedProcess(command, 130, "", output)
        except (FnSyncError, OSError) as exc:
            output = sanitize_output(str(exc)) + "\n"
            result = subprocess.CompletedProcess(command, 2, "", output)
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        rotate_task_log(log_path)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n===== {started} {status_action} dry_run={dry_run} =====\n")
            log.write(output)
            if output and not output.endswith("\n"):
                log.write("\n")
        with contextlib.suppress(PermissionError):
            log_path.chmod(0o600)
        state = "ok" if result.returncode == 0 else ("cancelled" if result.returncode == 130 else "error")
        message = tr("Complete", "完成") if result.returncode == 0 else failure_summary(output)
        update_status(
            task["id"],
            state=state,
            action=status_action,
            finished_at=now_iso(),
            exit_code=result.returncode,
            message=message,
            dry_run=dry_run,
            planned_changes=planned_change_count(output) if dry_run else 0,
            **details,
        )
        return CommandResult(
            result.returncode,
            output,
            command,
            streamed=os.environ.get("FNSYNC_STREAM_OUTPUT") == "1",
        )


def last_meaningful_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:500] if lines else tr("Sync failed; see the log for details", "同步失败；请查看日志")


def rotate_task_log(path: Path, max_bytes: int = MAX_TASK_LOG_BYTES) -> None:
    """Keep one bounded previous task log instead of growing without limit."""
    try:
        if path.stat().st_size <= max_bytes:
            return
    except FileNotFoundError:
        return
    rotated = path.with_suffix(path.suffix + ".1")
    with contextlib.suppress(FileNotFoundError):
        rotated.unlink()
    path.replace(rotated)
    if rotated.stat().st_size > max_bytes:
        with rotated.open("rb") as source:
            source.seek(-max_bytes, os.SEEK_END)
            tail = source.read()
        newline = tail.find(b"\n")
        if newline >= 0:
            tail = tail[newline + 1 :]
        with rotated.open("wb") as destination:
            destination.write(tail)
    with contextlib.suppress(PermissionError):
        rotated.chmod(0o600)


def access_marker_text(task: dict[str, Any]) -> str:
    return f"fn-sync access marker for task {task['id']}\n"


def _remote_marker_read(task: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    binary = require_rclone()
    with task_rclone_config(task) as config_path:
        command = [
            binary,
            "cat",
            remote_spec(task, ACCESS_MARKER),
            "--config",
            str(config_path),
            "--contimeout",
            "15s",
            "--timeout",
            "30s",
            "--disable-http2",
        ]
        if task.get("insecure_skip_verify"):
            command.append("--no-check-certificate")
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FnSyncError(
                tr(
                    "The NAS safety preflight timed out; FN sync will retry later.",
                    "NAS 安全预检超时；飞牛稍后将重试。",
                )
            ) from exc


def verify_access_markers(task: dict[str, Any]) -> None:
    expected = access_marker_text(task)
    marker = Path(task["local_path"]) / ACCESS_MARKER
    try:
        local_value = marker.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise AccessMarkerError(
            tr(
                "Safety check paused this task because its local FN sync marker is missing. No files were changed. Confirm both task folders, then repair the safety check.",
                "安全检查已暂停此任务，因为本地飞牛同步标记缺失。未修改任何文件。请确认任务两端文件夹无误，然后修复安全检查。",
            )
        ) from exc
    if local_value != expected:
        raise AccessMarkerError(
            tr(
                "Safety check paused this task because its local FN sync marker changed. No files were changed. Confirm both task folders, then repair the safety check.",
                "安全检查已暂停此任务，因为本地飞牛同步标记已更改。未修改任何文件。请确认任务两端文件夹无误，然后修复安全检查。",
            )
        )

    result = _remote_marker_read(task)
    output = sanitize_output((result.stdout or "") + (result.stderr or ""))
    if result.returncode:
        missing = any(
            phrase in output.lower()
            for phrase in ("not found", "directory not found", "object not found", "404")
        )
        if missing:
            raise AccessMarkerError(
                tr(
                    "Safety check paused this task because its NAS FN sync marker is missing. No files were changed. Confirm both task folders, then repair the safety check.",
                    "安全检查已暂停此任务，因为 NAS 上的飞牛同步标记缺失。未修改任何文件。请确认任务两端文件夹无误，然后修复安全检查。",
                )
            )
        raise FnSyncError(failure_summary(output))
    if result.stdout != expected:
        raise AccessMarkerError(
            tr(
                "Safety check paused this task because its NAS FN sync marker changed. No files were changed. Confirm both task folders, then repair the safety check.",
                "安全检查已暂停此任务，因为 NAS 上的飞牛同步标记已更改。未修改任何文件。请确认任务两端文件夹无误，然后修复安全检查。",
            )
        )


def pause_for_access_marker(task: dict[str, Any], error: AccessMarkerError) -> None:
    detected_at = now_iso()
    store = load_store()
    saved = find_task(store, task["id"])
    saved["enabled"] = False
    saved["safety_issue"] = {
        "code": error.error_code,
        "detected_at": detected_at,
    }
    saved["updated_at"] = detected_at
    save_store(store)
    update_status(
        task["id"],
        state="error",
        action="safety-check",
        started_at=detected_at,
        finished_at=detected_at,
        exit_code=2,
        error_code=error.error_code,
        message=str(error),
        dry_run=False,
        planned_changes=0,
    )


def preflight_access_markers(task: dict[str, Any]) -> None:
    try:
        verify_access_markers(task)
    except AccessMarkerError as exc:
        pause_for_access_marker(task, exc)
        raise


def ensure_access_markers(task: dict[str, Any]) -> CommandResult:
    local = Path(task["local_path"])
    local.mkdir(parents=True, exist_ok=True)
    marker = local / ACCESS_MARKER
    marker.write_text(access_marker_text(task), encoding="utf-8")
    marker.chmod(0o600)
    result = run_rclone(
        task,
        [
            "copyto",
            str(marker),
            remote_spec(task, ACCESS_MARKER),
            "--config",
            str(runtime_paths()["rclone"]),
            "--disable-http2",
            "--ignore-times",
        ] + (["--no-check-certificate"] if task.get("insecure_skip_verify") else []),
        status_action="access-check-setup",
    )
    if result.returncode:
        raise FnSyncError(last_meaningful_line(result.output))
    verify_access_markers(task)
    return result


def repair_access_markers(task: dict[str, Any], *, resume: bool = False) -> CommandResult:
    if task["mode"] != "two-way" or not task.get("initialized"):
        raise FnSyncError(
            tr(
                "Only an initialized two-way task can repair its safety check.",
                "只有已初始化的双向任务才能修复安全检查。",
            )
        )
    result = ensure_access_markers(task)
    legacy = Path(task["local_path"]) / LEGACY_ACCESS_MARKER
    with contextlib.suppress(FileNotFoundError):
        legacy.unlink()
    store = load_store()
    saved = find_task(store, task["id"])
    saved["enabled"] = bool(resume)
    saved.pop("safety_issue", None)
    saved["updated_at"] = now_iso()
    save_store(store)
    message = tr(
        "Safety check repaired and automatic sync resumed." if resume else "Safety check repaired; automatic sync remains paused.",
        "安全检查已修复，并已恢复自动同步。" if resume else "安全检查已修复；自动同步仍处于暂停状态。",
    )
    update_status(
        task["id"],
        state="ok",
        action="repair-access",
        finished_at=now_iso(),
        exit_code=0,
        message=message,
        dry_run=False,
        planned_changes=0,
    )
    return CommandResult(0, message + "\n", result.command)


def winner_to_resync_mode(winner: str) -> str:
    return {"local": "path1", "nas": "path2"}[winner]


def run_task(task: dict[str, Any], *, dry_run: bool = False) -> CommandResult:
    local = Path(task["local_path"])
    if not local.exists() or not local.is_dir():
        raise FnSyncError(tr(f"The local folder does not exist: {local}", f"本地目录不存在: {local}"))
    if task["mode"] == "two-way":
        if not task.get("initialized"):
            raise FnSyncError(tr("Complete Check first sync and Start first sync before running this task", "请先完成“检查首次同步”和“开始首次同步”，再运行此任务"))
        preflight_access_markers(task)
        args = bisync_args(task)
    else:
        args = one_way_args(task)
    result = run_rclone(task, args, dry_run=dry_run)
    if task["mode"] == "two-way" and result.returncode and is_access_marker_failure(result.output):
        pause_for_access_marker(task, AccessMarkerError(failure_summary(result.output)))
    return result


def preview_initial(task: dict[str, Any], winner: str) -> CommandResult:
    store = load_store()
    saved = find_task(store, task["id"])
    if saved.pop("first_sync_check", None) is not None:
        saved["updated_at"] = now_iso()
        save_store(store)
    # --check-access cannot be used before access markers exist. Build a normal
    # command and remove only that safety check for this non-mutating preview.
    args = bisync_args(task, initial=winner_to_resync_mode(winner))
    index = args.index("--check-access")
    del args[index : index + 3]
    result = run_rclone(
        task,
        args,
        dry_run=True,
        status_action="initial-preview",
        status_details={"conflict_winner": winner},
    )
    if result.returncode == 0:
        store = load_store()
        saved = find_task(store, task["id"])
        saved["first_sync_check"] = {
            "conflict_winner": winner,
            "checked_at": now_iso(),
            "planned_changes": planned_change_count(result.output),
        }
        saved["updated_at"] = now_iso()
        save_store(store)
    return result


def require_matching_first_sync_check(task: dict[str, Any], winner: str) -> None:
    check = task.get("first_sync_check") or {}
    if check.get("conflict_winner") != winner:
        raise FnSyncError(
            tr(
                "Run Check first sync with the same conflict rule before starting the first sync",
                "请先使用相同的冲突规则完成“检查首次同步”，再开始首次同步",
            )
        )


def initialize_task(task: dict[str, Any], winner: str) -> CommandResult:
    if task["mode"] != "two-way":
        raise FnSyncError(tr("Only two-way tasks need initialization", "只有双向任务需要初始化"))
    require_matching_first_sync_check(task, winner)
    ensure_access_markers(task)
    result = run_rclone(
        task,
        bisync_args(task, initial=winner_to_resync_mode(winner)),
        status_action="initialize",
        status_details={"conflict_winner": winner},
    )
    if result.returncode == 0:
        store = load_store()
        saved = find_task(store, task["id"])
        saved["initialized"] = True
        saved["enabled"] = True
        saved.pop("first_sync_check", None)
        saved["updated_at"] = now_iso()
        save_store(store)
    return result


def test_remote(task: dict[str, Any]) -> CommandResult:
    args = [
        "lsd",
        remote_spec(task),
        "--max-depth",
        "1",
        "--config",
        str(runtime_paths()["rclone"]),
    ]
    if task.get("insecure_skip_verify"):
        args.append("--no-check-certificate")
    return run_rclone(task, args, status_action="connection-test")


def connection_runtime_task(connection: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"connection-{connection['id']}",
        "name": connection["name"],
        "connection_id": connection["id"],
        "remote_name": connection["remote_name"],
        "remote_path": "",
        "credential_backend": connection["credential_backend"],
        "secret_attribute": connection.get("secret_attribute", "connection"),
        "secret_id": connection.get("secret_id", connection["id"]),
        "insecure_skip_verify": bool(connection.get("insecure_skip_verify")),
        "interval_seconds": 300,
        "filters": [],
    }


def test_connection(connection: dict[str, Any]) -> CommandResult:
    task = connection_runtime_task(connection)
    args = [
        "lsd",
        f"{connection['remote_name']}:",
        "--max-depth",
        "1",
        "--config",
        str(runtime_paths()["rclone"]),
    ]
    if connection.get("insecure_skip_verify"):
        args.append("--no-check-certificate")
    return run_rclone(task, args, status_action="connection-test")


def public_task(task: dict[str, Any]) -> dict[str, Any]:
    hidden = {
        "remote_name",
        "credential_backend",
        "secret_attribute",
        "secret_id",
        "allow_http",
        "insecure_skip_verify",
    }
    return {key: value for key, value in task.items() if key not in hidden}


def merged_task_status(
    store: dict[str, Any], task: dict[str, Any], status: dict[str, Any]
) -> dict[str, Any]:
    item = public_task(hydrate_task(store, task))
    task_status = dict(status.get("tasks", {}).get(task["id"], {"state": "never"}))
    if task_status.get("message") in {"Complete", "完成"}:
        task_status["message"] = tr("Complete", "完成")
    item["status"] = task_status
    return item


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "rclone": None,
        "gtk4": bool(shutil.which("gtk4-launch")),
        "gjs": bool(shutil.which("gjs")),
        "secret_service": bool(shutil.which("secret-tool")),
        "systemd_user": bool(shutil.which("systemctl")),
        "paths": {key: str(value) for key, value in runtime_paths().items()},
    }
    ok = True
    try:
        checks["rclone"] = ".".join(map(str, rclone_version()))
        checks["rclone_supported"] = tuple(map(int, checks["rclone"].split("."))) >= MIN_RCLONE_VERSION
        ok = bool(checks["rclone_supported"])
    except FnSyncError as exc:
        checks["rclone_error"] = str(exc)
        ok = False
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {checks['python']}")
        print(f"rclone: {checks.get('rclone') or checks.get('rclone_error')}")
        print(f"GTK/GJS: {checks['gtk4']}/{checks['gjs']}")
        print(f"systemd --user: {checks['systemd_user']}")
    return 0 if ok else 1


def validate_connection_name(raw: str) -> str:
    name = raw.strip()
    if not name or any(char in name for char in ("\n", "\r")):
        raise FnSyncError(tr("The NAS connection name cannot be empty or contain a newline", "NAS 连接名称不能为空或包含换行"))
    return name


def validate_username(raw: str) -> str:
    username = raw.strip()
    if not username or any(char in username for char in ("\n", "\r")):
        raise FnSyncError(tr("The WebDAV username cannot be empty or contain a newline", "WebDAV 用户名不能为空或包含换行"))
    return username


def password_from_args(args: argparse.Namespace, *, required: bool) -> str | None:
    if getattr(args, "password_stdin", False):
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise FnSyncError(tr("The password cannot be empty", "密码不能为空"))
        return password
    if not required:
        return None
    password = getpass.getpass(tr("WebDAV password: ", "WebDAV 密码: "))
    if not password:
        raise FnSyncError(tr("The password cannot be empty", "密码不能为空"))
    return password


def create_connection(
    store: dict[str, Any],
    *,
    name: str,
    url: str,
    username: str,
    password: str,
    allow_http: bool,
    insecure_skip_verify: bool,
) -> dict[str, Any]:
    name = validate_connection_name(name)
    url = validate_url(url, allow_http)
    username = validate_username(username)
    for existing in store["connections"]:
        if existing.get("url") == url and existing.get("username") == username:
            raise FnSyncError(
                tr(
                    f"This NAS and user are already saved as {existing['name']}; reuse that connection",
                    f"此 NAS 和用户已保存为连接 {existing['name']}；请直接复用该连接",
                )
            )
    connection_id = uuid.uuid4().hex[:12]
    remote_name = f"fnsync_nas_{connection_id}"
    credential_backend = store_remote(
        remote_name,
        connection_id,
        name,
        url,
        username,
        password,
    )
    connection = {
        "id": connection_id,
        "name": name,
        "url": url,
        "username": username,
        "remote_name": remote_name,
        "credential_backend": credential_backend,
        "secret_attribute": "connection",
        "secret_id": connection_id,
        "allow_http": bool(allow_http),
        "insecure_skip_verify": bool(insecure_skip_verify),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    store["connections"].append(connection)
    return connection


def cmd_connection_add(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    store = load_store()
    password = password_from_args(args, required=True)
    assert password is not None
    verify_unsaved_connection(
        args.url,
        args.username,
        password,
        allow_http=bool(args.allow_http),
        insecure_skip_verify=bool(args.insecure_skip_verify),
    )
    connection = create_connection(
        store,
        name=args.name,
        url=args.url,
        username=args.username,
        password=password,
        allow_http=bool(args.allow_http),
        insecure_skip_verify=bool(args.insecure_skip_verify),
    )
    try:
        save_store(store)
    except Exception:
        remove_remote(
            connection["remote_name"],
            connection["secret_id"],
            connection["credential_backend"],
            connection["secret_attribute"],
        )
        raise
    print(json.dumps(public_connection(connection), ensure_ascii=False))
    return 0


def cmd_connection_list(args: argparse.Namespace) -> int:
    connections = [public_connection(item) for item in load_store()["connections"]]
    if args.json:
        print(json.dumps(connections, ensure_ascii=False, indent=2))
    elif not connections:
        print(tr("No NAS connections yet", "还没有 NAS 连接"))
    else:
        for item in connections:
            print(f"{item['id']}  {item['name']}  {item['username']}@{item['url']}")
    return 0


def cmd_connection_test(args: argparse.Namespace) -> int:
    store = load_store()
    connection = find_connection(store, args.connection_id)
    return print_result(test_connection(connection), json_output=args.json)


def print_folder_listing(path: str, folders: list[dict[str, str]], *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"ok": True, "path": path, "folders": folders}, ensure_ascii=False))
    elif not folders:
        print(tr("No subfolders", "没有子文件夹"))
    else:
        for item in folders:
            print(item["path"])
    return 0


def cmd_connection_folders(args: argparse.Namespace) -> int:
    store = load_store()
    connection = find_connection(store, args.connection_id)
    path = normalize_browse_path(args.path or "")
    folders = browse_saved_connection(connection, path)
    return print_folder_listing(path, folders, json_output=args.json)


def cmd_connection_verify(args: argparse.Namespace) -> int:
    password = password_from_args(args, required=True)
    assert password is not None
    path = normalize_browse_path(args.path or "")
    folders = verify_unsaved_connection(
        args.url,
        args.username,
        password,
        allow_http=bool(args.allow_http),
        insecure_skip_verify=bool(args.insecure_skip_verify),
        raw_path=path,
    )
    return print_folder_listing(path, folders, json_output=args.json)


def cmd_connection_update(args: argparse.Namespace) -> int:
    store = load_store()
    connection = find_connection(store, args.connection_id)
    previous_connection = dict(connection)
    name = validate_connection_name(args.name if args.name is not None else connection["name"])
    allow_http = (
        bool(args.allow_http)
        if args.allow_http is not None
        else bool(connection.get("allow_http"))
    )
    url = validate_url(args.url if args.url is not None else connection["url"], allow_http)
    username = validate_username(
        args.username if args.username is not None else connection["username"]
    )
    insecure = (
        bool(args.insecure_skip_verify)
        if args.insecure_skip_verify is not None
        else bool(connection.get("insecure_skip_verify"))
    )
    for existing in store["connections"]:
        if existing["id"] == connection["id"]:
            continue
        if existing.get("url") == url and existing.get("username") == username:
            raise FnSyncError(tr(f"The same NAS and user are already saved as {existing['name']}", f"相同的 NAS 和用户已保存为连接 {existing['name']}"))

    password = password_from_args(args, required=False)
    if password is not None:
        previous_backend = connection["credential_backend"]
        backend = store_remote(
            connection["remote_name"],
            connection.get("secret_id", connection["id"]),
            name,
            url,
            username,
            password,
            connection.get("secret_attribute", "connection"),
        )
        if previous_backend == "secret-service" and backend != previous_backend:
            secret_tool_clear(
                connection.get("secret_id", connection["id"]),
                connection.get("secret_attribute", "connection"),
            )
        connection["credential_backend"] = backend
    else:
        parser = _load_rclone_config()
        if not parser.has_section(connection["remote_name"]):
            raise FnSyncError(tr("The NAS connection's rclone configuration does not exist", "NAS 连接的 rclone 配置不存在"))
        parser[connection["remote_name"]]["url"] = url
        parser[connection["remote_name"]]["user"] = username
        _write_rclone_config(parser)

    connection.update(
        {
            "name": name,
            "url": url,
            "username": username,
            "allow_http": allow_http,
            "insecure_skip_verify": insecure,
            "updated_at": now_iso(),
        }
    )
    check_invalidated = any(
        connection.get(key) != previous_connection.get(key)
        for key in ("url", "username", "allow_http", "insecure_skip_verify")
    ) or password is not None
    if check_invalidated:
        for task in store["tasks"]:
            if task.get("connection_id") == connection["id"]:
                task.pop("first_sync_check", None)
    save_store(store)
    print(json.dumps(public_connection(connection), ensure_ascii=False))
    return 0


def cmd_connection_remove(args: argparse.Namespace) -> int:
    store = load_store()
    connection = find_connection(store, args.connection_id)
    used_by = [task for task in store["tasks"] if task.get("connection_id") == connection["id"]]
    if used_by:
        names = ", ".join(str(task.get("name") or task["id"]) for task in used_by[:3])
        raise FnSyncError(tr(f"The NAS connection is still used by sync tasks: {names}", f"NAS 连接仍被同步任务使用: {names}"))
    store["connections"] = [
        item for item in store["connections"] if item["id"] != connection["id"]
    ]
    save_store(store)
    remove_remote(
        connection["remote_name"],
        connection.get("secret_id", connection["id"]),
        connection.get("credential_backend", "rclone-obscured"),
        connection.get("secret_attribute", "connection"),
    )
    print(tr("NAS connection removed; no synced files were deleted.", "NAS 连接已移除；同步文件未被删除。"))
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    local = validate_local_path(args.local)
    remote_path = validate_remote_path(args.remote_path)
    interval = validate_interval(args.interval)
    bwlimit = validate_bwlimit(args.bwlimit)
    name = args.name.strip()
    if not name:
        raise FnSyncError(tr("The task name cannot be empty", "任务名称不能为空"))
    if any("\n" in rule or "\r" in rule for rule in (args.filter or [])):
        raise FnSyncError(tr("Each custom filter rule must be a single line", "每个自定义过滤规则必须是单行"))
    if args.mode not in MODES:
        raise FnSyncError(tr("Unknown sync mode", "未知同步模式"))
    store = load_store()
    created_connection: dict[str, Any] | None = None
    if args.connection:
        connection = find_connection(store, args.connection)
    else:
        if not args.url or not args.username:
            raise FnSyncError(tr("Select a saved NAS connection with --connection", "请通过 --connection 选择已保存的 NAS 连接"))
        password = password_from_args(args, required=True)
        assert password is not None
        created_connection = create_connection(
            store,
            name=args.connection_name or f"{name} NAS",
            url=args.url,
            username=args.username,
            password=password,
            allow_http=bool(args.allow_http),
            insecure_skip_verify=bool(args.insecure_skip_verify),
        )
        connection = created_connection
    validate_task_isolation(store, local, connection["id"], remote_path)
    local.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "name": name,
        "connection_id": connection["id"],
        "enabled": False,
        "mode": args.mode,
        "local_path": str(local),
        "remote_path": remote_path,
        "interval_seconds": interval,
        "bwlimit": bwlimit,
        "filters": list(args.filter or []),
        "initialized": args.mode != "two-way",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    store["tasks"].append(task)
    try:
        filter_file(task)
        save_store(store)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            (runtime_paths()["filters"] / f"{task_id}.rules").unlink()
        if created_connection is not None:
            remove_remote(
                created_connection["remote_name"],
                created_connection["secret_id"],
                created_connection["credential_backend"],
                created_connection["secret_attribute"],
            )
        raise
    print(json.dumps(public_task(hydrate_task(store, task)), ensure_ascii=False))
    return 0


def cmd_task_list(args: argparse.Namespace) -> int:
    store = load_store()
    status = load_status()
    tasks = [merged_task_status(store, task, status) for task in store["tasks"]]
    if args.json:
        print(json.dumps(tasks, ensure_ascii=False, indent=2))
    elif not tasks:
        print(tr("No sync tasks yet", "还没有同步任务"))
    else:
        for task in tasks:
            state = task["status"].get("state", "never")
            enabled = tr("enabled", "启用") if task["enabled"] else tr("paused", "暂停")
            print(f"{task['id']}  {task['name']}  {task['mode']}  {enabled}  {state}")
    return 0


def _task_from_args(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    store = load_store()
    return store, find_task(store, args.task_id)


def print_result(result: CommandResult, *, json_output: bool = False) -> int:
    if json_output:
        print(
            json.dumps(
                {"ok": result.returncode == 0, "exit_code": result.returncode, "output": result.output},
                ensure_ascii=False,
            )
        )
    elif result.output and not result.streamed:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    return result.returncode


def cmd_task_test(args: argparse.Namespace) -> int:
    store, task = _task_from_args(args)
    return print_result(test_remote(hydrate_task(store, task)), json_output=args.json)


def cmd_task_preview(args: argparse.Namespace) -> int:
    store, saved = _task_from_args(args)
    task = hydrate_task(store, saved)
    if task["mode"] == "two-way" and not task.get("initialized"):
        if not args.winner:
            raise FnSyncError(tr("Check first sync requires --winner local or --winner nas", "“检查首次同步”需要通过 --winner local 或 --winner nas 选择冲突规则"))
        result = preview_initial(task, args.winner)
    else:
        result = run_task(task, dry_run=True)
    return print_result(result, json_output=args.json)


def cmd_task_initialize(args: argparse.Namespace) -> int:
    store, saved = _task_from_args(args)
    task = hydrate_task(store, saved)
    if not args.winner:
        raise FnSyncError(tr("Start first sync requires --winner local or --winner nas", "“开始首次同步”需要通过 --winner local 或 --winner nas 选择冲突规则"))
    if not args.apply:
        print(tr("No changes were written. Complete Check first sync, then add --apply to confirm.", "未执行写入。请先完成“检查首次同步”，确认后再追加 --apply。"), file=sys.stderr)
        return print_result(preview_initial(task, args.winner), json_output=args.json)
    return print_result(initialize_task(task, args.winner), json_output=args.json)


def cmd_task_run(args: argparse.Namespace) -> int:
    store, task = _task_from_args(args)
    return print_result(
        run_task(hydrate_task(store, task), dry_run=args.dry_run),
        json_output=args.json,
    )


def cmd_task_repair_access(args: argparse.Namespace) -> int:
    store, task = _task_from_args(args)
    return print_result(
        repair_access_markers(hydrate_task(store, task), resume=bool(args.resume)),
        json_output=args.json,
    )


def cmd_task_toggle(args: argparse.Namespace, enabled: bool) -> int:
    store, task = _task_from_args(args)
    if enabled and task["mode"] == "two-way" and not task.get("initialized"):
        raise FnSyncError(tr("Initialize the two-way task before enabling background sync", "双向任务初始化后才能启用后台同步"))
    if enabled and (task.get("safety_issue") or {}).get("code") == "access-marker":
        raise FnSyncError(
            tr(
                "Repair this task's safety check before resuming automatic sync.",
                "请先修复此任务的安全检查，再恢复自动同步。",
            )
        )
    if enabled and task["mode"] == "two-way":
        preflight_access_markers(hydrate_task(store, task))
    task["enabled"] = enabled
    task["updated_at"] = now_iso()
    save_store(store)
    print("enabled" if enabled else "disabled")
    return 0


def cmd_task_remove(args: argparse.Namespace) -> int:
    store, task = _task_from_args(args)
    store["tasks"] = [item for item in store["tasks"] if item["id"] != task["id"]]
    save_store(store)
    with contextlib.suppress(FileNotFoundError):
        (runtime_paths()["filters"] / f"{task['id']}.rules").unlink()
    print(tr("Task removed; local and NAS files were kept.", "任务已移除；本地和 NAS 文件均未删除。"))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = load_store()
    status = load_status()
    payload = [merged_task_status(store, task, status) for task in store["tasks"]]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for task in payload:
            print(f"{task['name']}: {task['status'].get('state', 'never')} {task['status'].get('message', '')}")
    return 0


def cmd_sync_now(args: argparse.Namespace) -> int:
    store = load_store()
    results: list[dict[str, Any]] = []
    for task in store["tasks"]:
        if not task.get("enabled"):
            continue
        try:
            result = run_task(hydrate_task(store, task))
            results.append(
                {
                    "id": task["id"],
                    "name": task["name"],
                    "ok": result.returncode == 0,
                    "exit_code": result.returncode,
                    "message": tr("Complete", "完成") if result.returncode == 0 else failure_summary(result.output),
                }
            )
        except FnSyncError as exc:
            results.append(
                {"id": task["id"], "name": task["name"], "ok": False, "exit_code": 2, "message": str(exc)}
            )
    ok = all(item["ok"] for item in results)
    payload = {"ok": ok, "count": len(results), "results": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    elif not results:
        print(tr("No enabled sync tasks", "没有已启用的同步任务"))
    else:
        for item in results:
            print(f"{item['name']}: {item['message']}")
    return 0 if ok else 1


def cmd_logs(args: argparse.Namespace) -> int:
    _, task = _task_from_args(args)
    path = runtime_paths()["logs"] / f"{task['id']}.log"
    if not path.exists():
        print(tr("No logs yet", "还没有日志"))
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-args.lines :]))
    return 0


def daemon_loop(once: bool = False) -> int:
    stop = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    due: dict[str, float] = {}
    while not stop:
        store = load_store()
        now = time.monotonic()
        for task in store["tasks"]:
            if not task.get("enabled"):
                continue
            if now < due.get(task["id"], 0):
                continue
            try:
                result = run_task(hydrate_task(store, task))
                if result.returncode and shutil.which("notify-send"):
                    subprocess.run(
                        ["notify-send", tr("FN sync failed", "飞牛同步失败"), f"{task['name']}: {failure_summary(result.output)}"],
                        check=False,
                    )
            except TaskBusyError:
                # A manual run owns the task. Let it publish the final status.
                pass
            except FnSyncError as exc:
                update_status(task["id"], state="error", finished_at=now_iso(), message=str(exc))
            due[task["id"]] = now + int(task.get("interval_seconds", 300))
        if once:
            return 0
        for _ in range(10):
            if stop:
                break
            time.sleep(1)
    return 0


def cmd_ui(_args: argparse.Namespace) -> int:
    gjs = shutil.which("gjs")
    if not gjs:
        raise FnSyncError(tr("GJS was not found, so the GTK client cannot start", "未找到 GJS，无法启动 GTK 界面"))
    candidates = [
        Path("/usr/share/fn-sync/ui/app.js"),
        Path("/usr/share/fnsync/ui/app.js"),
        data_dir() / "ui" / "app.js",
        Path(__file__).resolve().parents[1] / "ui" / "app.js",
    ]
    ui = next((path for path in candidates if path.exists()), None)
    if not ui:
        raise FnSyncError(tr("The graphical interface file could not be found", "找不到图形界面文件"))
    os.environ["FNSYNC_CONTROLLER"] = str(Path(__file__).resolve())
    os.execv(gjs, [gjs, "-m", str(ui)])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fn-sync", description=tr("fnOS Linux file sync client", "fnOS Linux 文件同步客户端"))
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help=tr("check the runtime environment", "检查运行环境"))
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    connection = sub.add_parser("connection", help=tr("manage reusable NAS connections and authorization", "管理可复用的 NAS 连接和授权"))
    connection_sub = connection.add_subparsers(dest="connection_command", required=True)

    connection_add = connection_sub.add_parser("add", help=tr("connect and authorize a NAS", "连接并授权一台 NAS"))
    connection_add.add_argument("--name", required=True)
    connection_add.add_argument("--url", required=True)
    connection_add.add_argument("--username", required=True)
    connection_add.add_argument("--password-stdin", action="store_true")
    connection_add.add_argument("--allow-http", action="store_true")
    connection_add.add_argument("--insecure-skip-verify", action="store_true")
    connection_add.set_defaults(func=cmd_connection_add)

    connection_list = connection_sub.add_parser("list", help=tr("list NAS connections", "列出 NAS 连接"))
    connection_list.add_argument("--json", action="store_true")
    connection_list.set_defaults(func=cmd_connection_list)

    connection_test = connection_sub.add_parser("test", help=tr("test a NAS connection", "测试 NAS 连接"))
    connection_test.add_argument("connection_id")
    connection_test.add_argument("--json", action="store_true")
    connection_test.set_defaults(func=cmd_connection_test)

    connection_folders = connection_sub.add_parser("folders", help=tr("browse folders on a saved NAS connection", "浏览已保存 NAS 连接中的文件夹"))
    connection_folders.add_argument("connection_id")
    connection_folders.add_argument("--path", default="")
    connection_folders.add_argument("--json", action="store_true")
    connection_folders.set_defaults(func=cmd_connection_folders)

    connection_verify = connection_sub.add_parser("verify", help=tr("test credentials without saving them", "测试凭据但不保存"))
    connection_verify.add_argument("--url", required=True)
    connection_verify.add_argument("--username", required=True)
    connection_verify.add_argument("--password-stdin", action="store_true")
    connection_verify.add_argument("--path", default="")
    connection_verify.add_argument("--allow-http", action="store_true")
    connection_verify.add_argument("--insecure-skip-verify", action="store_true")
    connection_verify.add_argument("--json", action="store_true")
    connection_verify.set_defaults(func=cmd_connection_verify)

    connection_update = connection_sub.add_parser("update", help=tr("update a connection or reauthorize", "更新连接或重新授权"))
    connection_update.add_argument("connection_id")
    connection_update.add_argument("--name")
    connection_update.add_argument("--url")
    connection_update.add_argument("--username")
    connection_update.add_argument("--password-stdin", action="store_true")
    http_group = connection_update.add_mutually_exclusive_group()
    http_group.add_argument("--allow-http", action="store_true", dest="allow_http")
    http_group.add_argument("--require-https", action="store_false", dest="allow_http")
    connection_update.set_defaults(allow_http=None)
    tls_group = connection_update.add_mutually_exclusive_group()
    tls_group.add_argument(
        "--insecure-skip-verify", action="store_true", dest="insecure_skip_verify"
    )
    tls_group.add_argument("--verify-tls", action="store_false", dest="insecure_skip_verify")
    connection_update.set_defaults(insecure_skip_verify=None)
    connection_update.set_defaults(func=cmd_connection_update)

    connection_remove = connection_sub.add_parser("remove", help=tr("remove an unused NAS connection", "移除未使用的 NAS 连接"))
    connection_remove.add_argument("connection_id")
    connection_remove.set_defaults(func=cmd_connection_remove)

    task = sub.add_parser("task", help=tr("manage sync tasks", "管理同步任务"))
    task_sub = task.add_subparsers(dest="task_command", required=True)

    add = task_sub.add_parser("add", help=tr("add a task", "添加任务"))
    add.add_argument("--name", required=True)
    add.add_argument("--mode", choices=MODES, default="two-way")
    add.add_argument("--local", required=True)
    add.add_argument("--connection", help=tr("saved NAS connection ID", "已保存的 NAS 连接 ID"))
    add.add_argument("--url", help=tr("compatibility mode: WebDAV URL used to create a connection", "兼容模式：创建连接时使用的 WebDAV URL"))
    add.add_argument("--remote-path", required=True)
    add.add_argument("--username", help=tr("compatibility mode: username used to create a connection", "兼容模式：创建连接时使用的用户名"))
    add.add_argument("--connection-name", help=tr("compatibility mode: new NAS connection name", "兼容模式：新 NAS 连接名称"))
    add.add_argument("--password-stdin", action="store_true")
    add.add_argument("--interval", type=int, default=300)
    add.add_argument("--bwlimit")
    add.add_argument("--filter", action="append")
    add.add_argument("--allow-http", action="store_true")
    add.add_argument("--insecure-skip-verify", action="store_true")
    add.set_defaults(func=cmd_task_add)

    listing = task_sub.add_parser("list", help=tr("list tasks", "列出任务"))
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_task_list)

    for name, func, help_text in (
        ("test", cmd_task_test, tr("test the NAS connection", "测试 NAS 连接")),
        ("preview", cmd_task_preview, tr("preview sync changes", "预览同步变化")),
        ("initialize", cmd_task_initialize, tr("initialize two-way sync", "初始化双向同步")),
        ("run", cmd_task_run, tr("sync now", "立即同步")),
    ):
        command = task_sub.add_parser(name, help=help_text)
        command.add_argument("task_id")
        command.add_argument("--json", action="store_true")
        if name in ("preview", "initialize"):
            command.add_argument(
                "--winner",
                choices=("local", "nas"),
                help=tr("authoritative side for same-name files in the first merge", "首次合并中同名文件以哪一端为准"),
            )
        if name == "initialize":
            command.add_argument("--apply", action="store_true")
        if name == "run":
            command.add_argument("--dry-run", action="store_true")
        command.set_defaults(func=func)

    repair_access = task_sub.add_parser(
        "repair-access",
        help=tr("repair and verify a two-way task's safety marker", "修复并验证双向任务的安全标记"),
    )
    repair_access.add_argument("task_id")
    repair_access.add_argument("--resume", action="store_true")
    repair_access.add_argument("--json", action="store_true")
    repair_access.set_defaults(func=cmd_task_repair_access)

    enable = task_sub.add_parser("enable", help=tr("enable background sync", "启用后台同步"))
    enable.add_argument("task_id")
    enable.set_defaults(func=lambda args: cmd_task_toggle(args, True))
    disable = task_sub.add_parser("disable", help=tr("pause background sync", "暂停后台同步"))
    disable.add_argument("task_id")
    disable.set_defaults(func=lambda args: cmd_task_toggle(args, False))
    remove = task_sub.add_parser("remove", help=tr("remove the task but keep files", "移除任务但保留文件"))
    remove.add_argument("task_id")
    remove.set_defaults(func=cmd_task_remove)

    status = sub.add_parser("status", help=tr("show task status", "显示任务状态"))
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    sync_now = sub.add_parser("sync-now", help=tr("run all enabled tasks now", "立即运行所有已启用的任务"))
    sync_now.add_argument("--json", action="store_true")
    sync_now.set_defaults(func=cmd_sync_now)

    logs = sub.add_parser("logs", help=tr("show task logs", "查看任务日志"))
    logs.add_argument("task_id")
    logs.add_argument("--lines", type=int, default=100)
    logs.set_defaults(func=cmd_logs)

    daemon = sub.add_parser("daemon", help=tr("run the background scheduler", "运行后台调度器"))
    daemon.add_argument("--once", action="store_true")
    daemon.set_defaults(func=lambda args: daemon_loop(args.once))

    ui = sub.add_parser("ui", help=tr("open the GTK interface", "打开 GTK 图形界面"))
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        ensure_runtime_dirs()
        return int(args.func(args))
    except FnSyncError as exc:
        print(tr(f"Error: {exc}", f"错误: {exc}"), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(tr("Canceled", "已取消"), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
