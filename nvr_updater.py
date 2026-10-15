from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from zipfile import BadZipFile, ZipFile


APP_EXE_NAME = "NVR Assistant.exe"


class UpdaterError(RuntimeError):
    pass


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _wait_for_process_exit(pid: int, timeout: float = 90.0) -> None:
    if os.name != "nt" or pid <= 0:
        return
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == wait_timeout:
            raise UpdaterError("等待原程序退出超时，请关闭程序后再次更新")
    finally:
        kernel32.CloseHandle(handle)


def _safe_extract(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    try:
        with ZipFile(archive_path) as archive:
            for member in archive.infolist():
                member_path = (destination / member.filename).resolve()
                if (
                    member_path != destination
                    and destination not in member_path.parents
                ):
                    raise UpdaterError("更新包包含非法路径")
            archive.extractall(destination)
    except BadZipFile as exc:
        raise UpdaterError("更新包不是有效的 ZIP 文件") from exc
    except OSError as exc:
        raise UpdaterError(f"解压更新包失败: {exc}") from exc


def _find_payload_root(extracted_dir: Path) -> Path:
    candidates = [extracted_dir]
    candidates.extend(
        child
        for child in extracted_dir.iterdir()
        if child.is_dir()
    )
    for candidate in candidates:
        if (candidate / APP_EXE_NAME).is_file():
            return candidate
    raise UpdaterError(f"更新包中找不到 {APP_EXE_NAME}")


def _replace_directory(source: Path, target: Path, pid: int) -> None:
    source = source.resolve()
    target = target.resolve()
    if not target.is_dir():
        raise UpdaterError(f"当前程序目录不存在: {target}")

    backup = target.with_name(f".{target.name}.backup-{pid}")
    if backup.exists():
        shutil.rmtree(backup)

    moved_target = False
    try:
        os.replace(target, backup)
        moved_target = True
        os.replace(source, target)
    except OSError as exc:
        if moved_target and not target.exists() and backup.exists():
            os.replace(backup, target)
        raise UpdaterError(f"替换程序目录失败: {exc}") from exc

    try:
        shutil.rmtree(backup)
    except OSError:
        # A stale backup is harmless and can be removed next time.
        pass


def _show_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "NVR Assistant 更新失败",
            0x00000010,
        )
    except Exception:
        pass


def _write_log(message: str) -> None:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    log_dir = Path(base) / "NVRAssistant" / "updates"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "update.log").open("a", encoding="utf-8") as output:
            output.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
            )
    except OSError:
        pass


def apply_update(
    archive_path: Path,
    target_dir: Path,
    parent_pid: int,
    restart: bool,
) -> None:
    archive_path = archive_path.resolve()
    target_dir = target_dir.resolve()
    if not archive_path.is_file():
        raise UpdaterError("更新包不存在")
    if not (target_dir / APP_EXE_NAME).is_file():
        raise UpdaterError(f"目标目录中没有 {APP_EXE_NAME}")

    staging = target_dir.with_name(f".{target_dir.name}.update-{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        _wait_for_process_exit(parent_pid)
        _safe_extract(archive_path, staging)
        payload = _find_payload_root(staging)
        _replace_directory(payload, target_dir, parent_pid)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    if restart:
        subprocess.Popen(
            [str(target_dir / APP_EXE_NAME)],
            cwd=str(target_dir),
            close_fds=True,
            creationflags=_creation_flags(),
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) != 6 or args[1] != "--apply-update":
        return 2

    try:
        archive_path = Path(args[2])
        target_dir = Path(args[3])
        parent_pid = int(args[4])
        restart = args[5] == "--restart"
        apply_update(archive_path, target_dir, parent_pid, restart)
        _write_log("更新完成")
        return 0
    except Exception as exc:
        _write_log(f"更新失败: {exc}")
        _show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
