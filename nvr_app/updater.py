from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


REPOSITORY = "paynehe3023/NVR-Assistant"
DEFAULT_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{REPOSITORY}/main/version.json"
)
RELEASE_API_URL = (
    f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
)
USER_AGENT = "nvr-assistant-updater"
HTTP_TIMEOUT = 20
CHUNK_SIZE = 256 * 1024
APP_EXE_NAME = "NVR.Assistant.exe"
LEGACY_APP_EXE_NAMES = ("NVR Assistant.exe",)
PAYLOAD_EXE_NAMES = (APP_EXE_NAME, *LEGACY_APP_EXE_NAMES)
UPDATE_MODE_ONEFILE = "onefile"
UPDATE_MODE_ONEDIR = "onedir"
PAYLOAD_ZIP = "zip"
PAYLOAD_EXE = "exe"


class UpdateError(RuntimeError):
    """An update error that is safe to show to the user."""


class UpdateCancelled(UpdateError):
    """Raised when the user cancels an update operation."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    notes: str = ""
    published_at: str = ""
    sha256: str = ""


def _version_key(value: str) -> tuple[int, int, int, int]:
    match = re.search(r"(\d+(?:\.\d+)*)", str(value).strip())
    if not match:
        raise UpdateError(f"无效版本号: {value}")
    parts = [int(part) for part in match.group(1).split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def is_newer(remote_version: str, current_version: str) -> bool:
    return _version_key(remote_version) > _version_key(current_version)


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, application/json",
        },
    )


def _emit(progress, event: dict) -> None:
    if progress is not None:
        progress(event)


def _check_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled("操作已取消")


def _read_json(url: str) -> dict:
    try:
        with urlopen(_request(url), timeout=HTTP_TIMEOUT) as response:
            raw = response.read()
    except HTTPError:
        raise
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"无法连接更新服务器: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("更新清单格式无效") from exc
    if not isinstance(payload, dict):
        raise UpdateError("更新清单必须是 JSON 对象")
    return payload


def _clean_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UpdateError("更新清单中的 sha256 无效")
    return digest


def _manifest_from_version_json(payload: dict) -> UpdateInfo:
    version = str(
        payload.get("version")
        or payload.get("latest_version")
        or payload.get("tag_name")
        or ""
    ).strip()
    download_url = str(
        payload.get("download_url")
        or payload.get("asset_url")
        or payload.get("url")
        or ""
    ).strip()
    if not version or not download_url:
        raise UpdateError("version.json 缺少 version 或 download_url")
    return UpdateInfo(
        version=version,
        download_url=download_url,
        notes=str(payload.get("notes") or payload.get("changelog") or "").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        sha256=_clean_sha256(payload.get("sha256")),
    )


def _manifest_from_release(payload: dict) -> UpdateInfo:
    version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    assets = payload.get("assets") or []
    download_assets = [
        asset
        for asset in assets
        if str(asset.get("name") or "").lower().endswith((".zip", ".exe"))
    ]
    exe_assets = [
        asset
        for asset in download_assets
        if str(asset.get("name") or "").lower().endswith(".exe")
    ]
    asset = exe_assets[0] if exe_assets else (
        download_assets[0] if download_assets else None
    )
    if not version or not asset:
        raise UpdateError("GitHub Release 缺少版本标签或 EXE/ZIP 资产")
    return UpdateInfo(
        version=version,
        download_url=str(asset.get("browser_download_url") or "").strip(),
        notes=str(payload.get("body") or "").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        sha256=_clean_sha256(asset.get("digest")),
    )


def check_for_update(
    current_version: str,
    manifest_url: str = DEFAULT_MANIFEST_URL,
    *,
    progress=None,
    cancel_event=None,
) -> UpdateInfo | None:
    """Return a newer release, or None when the current version is current."""
    _check_cancelled(cancel_event)
    _emit(progress, {"message": "正在检查更新", "indeterminate": True})
    try:
        payload = _read_json(manifest_url)
        info = _manifest_from_version_json(payload)
    except HTTPError as exc:
        if exc.code != 404:
            raise UpdateError(
                f"更新清单不可访问: HTTP {exc.code}"
            ) from exc
        _check_cancelled(cancel_event)
        try:
            payload = _read_json(RELEASE_API_URL)
            info = _manifest_from_release(payload)
        except HTTPError as release_exc:
            if release_exc.code == 404:
                raise UpdateError(
                    "仓库中还没有 version.json，也没有可用的 GitHub Release"
                ) from release_exc
            raise UpdateError(
                f"GitHub Release 不可访问: HTTP {release_exc.code}"
            ) from release_exc

    _check_cancelled(cancel_event)
    return info if is_newer(info.version, current_version) else None


def _update_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "NVRAssistant" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_name(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return name or "NVRAssistant-update"


def _update_payload_kind(path: Path) -> str:
    try:
        with open(path, "rb") as source:
            signature = source.read(2)
    except OSError as exc:
        raise UpdateError(f"无法读取更新文件: {exc}") from exc
    if signature == b"MZ":
        return PAYLOAD_EXE
    if signature == b"PK":
        return PAYLOAD_ZIP
    raise UpdateError("更新文件不是有效的 EXE 或 ZIP")


def download_update(
    url: str,
    expected_sha256: str = "",
    *,
    progress=None,
    cancel_event=None,
) -> Path:
    """Download a release EXE or ZIP and verify it before returning its path."""
    target = _update_dir() / _download_name(url)
    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)

    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(_request(url), timeout=HTTP_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with open(part, "wb") as output:
                while True:
                    _check_cancelled(cancel_event)
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    percent = (
                        min(100, int(received * 100 / total))
                        if total
                        else 0
                    )
                    _emit(
                        progress,
                        {
                            "message": "正在下载更新",
                            "downloaded": received,
                            "total": total,
                            "percent": percent,
                        },
                    )
    except HTTPError as exc:
        part.unlink(missing_ok=True)
        if exc.code == 404:
            raise UpdateError(
                "下载地址不存在（HTTP 404）：请确认 GitHub Release "
                "已上传更新文件，且 version.json 的 download_url 指向该文件"
            ) from exc
        raise UpdateError(f"下载更新失败: HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"下载更新失败: {exc}") from exc
    except UpdateCancelled:
        part.unlink(missing_ok=True)
        raise

    expected = _clean_sha256(expected_sha256)
    actual = digest.hexdigest()
    if expected and actual != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("更新文件校验失败，已删除下载内容")

    try:
        payload_kind = _update_payload_kind(part)
        if payload_kind == PAYLOAD_ZIP:
            with ZipFile(part) as archive:
                bad_file = archive.testzip()
                if bad_file:
                    raise UpdateError(f"更新包解压校验失败: {bad_file}")
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (BadZipFile, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError("下载内容不是有效的更新文件") from exc

    os.replace(part, target)
    _emit(
        progress,
        {
            "message": "更新包下载完成",
            "downloaded": received,
            "total": received,
            "percent": 100,
        },
    )
    return target


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
            raise UpdateError("等待原程序退出超时，请关闭程序后再次更新")
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
                    raise UpdateError("更新包包含非法路径")
            archive.extractall(destination)
    except BadZipFile as exc:
        raise UpdateError("更新包不是有效的 ZIP 文件") from exc
    except OSError as exc:
        raise UpdateError(f"解压更新包失败: {exc}") from exc


def _normalize_update_mode(mode: str | None) -> str:
    if mode in (None, ""):
        return ""
    value = str(mode).strip().lower()
    if value not in (UPDATE_MODE_ONEFILE, UPDATE_MODE_ONEDIR):
        raise UpdateError(f"无效更新模式: {mode}")
    return value


def _detect_update_mode(target_dir: Path) -> str:
    target_dir = Path(target_dir).resolve()
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            try:
                if Path(bundle_root).resolve() == (
                    target_dir / "_internal"
                ).resolve():
                    return UPDATE_MODE_ONEDIR
                return UPDATE_MODE_ONEFILE
            except OSError:
                pass
    if (target_dir / "_internal").is_dir():
        return UPDATE_MODE_ONEDIR
    return UPDATE_MODE_ONEFILE


def _find_payload_root(extracted_dir: Path) -> Path:
    candidates = [extracted_dir]
    candidates.extend(
        child
        for child in extracted_dir.iterdir()
        if child.is_dir()
    )
    for candidate in candidates:
        if any(
            (candidate / name).is_file()
            for name in PAYLOAD_EXE_NAMES
        ):
            return candidate
    raise UpdateError(f"更新包中找不到 {APP_EXE_NAME}")


def _find_payload_executable(payload_root: Path) -> Path:
    for name in PAYLOAD_EXE_NAMES:
        executable = payload_root / name
        if executable.is_file():
            return executable
    raise UpdateError(f"更新包中找不到 {APP_EXE_NAME}")


def _replace_file(source: Path, target: Path, token: str) -> None:
    source = source.resolve()
    target = target.resolve()
    if not target.is_file():
        raise UpdateError(f"当前程序文件不存在: {target}")

    backup = target.with_name(f".{target.name}.backup-{token}")
    if backup.exists():
        backup.unlink()

    moved_target = False
    try:
        os.replace(target, backup)
        moved_target = True
        os.replace(source, target)
    except OSError as exc:
        if moved_target and not target.exists() and backup.exists():
            os.replace(backup, target)
        raise UpdateError(f"替换程序文件失败: {exc}") from exc

    try:
        backup.unlink()
    except OSError:
        pass


def _replace_directory(source: Path, target: Path, token: str) -> None:
    source = source.resolve()
    target = target.resolve()
    if not target.is_dir():
        raise UpdateError(f"当前程序目录不存在: {target}")

    backup = target.with_name(f".{target.name}.backup-{token}")
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
        raise UpdateError(f"替换程序目录失败: {exc}") from exc

    try:
        shutil.rmtree(backup)
    except OSError:
        pass


def _write_update_log(message: str) -> None:
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


def _show_update_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "NVR Assistant 更新失败",
            0x00000010,
        )
    except (AttributeError, OSError):
        pass


def apply_update(
    archive_path: Path,
    target_dir: Path,
    parent_pid: int,
    restart: bool,
    mode: str | None = None,
    target_exe_name: str | None = None,
) -> None:
    """Install a verified EXE or ZIP after the parent process has exited."""
    archive_path = Path(archive_path).resolve()
    target_dir = Path(target_dir).resolve()
    update_mode = _normalize_update_mode(mode) or _detect_update_mode(
        target_dir
    )
    if not archive_path.is_file():
        raise UpdateError("更新包不存在")
    payload_kind = _update_payload_kind(archive_path)
    resolved_target_name = str(target_exe_name or APP_EXE_NAME).strip()
    if (
        not resolved_target_name
        or Path(resolved_target_name).name != resolved_target_name
    ):
        raise UpdateError("目标程序文件名无效")
    target_exe = target_dir / resolved_target_name
    if not target_exe.is_file():
        raise UpdateError(f"目标目录中没有 {resolved_target_name}")

    token = uuid.uuid4().hex
    staging = target_dir.parent / f".{target_dir.name}.update-{token}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        _wait_for_process_exit(parent_pid)
        if payload_kind == PAYLOAD_EXE:
            staged_exe = staging / resolved_target_name
            shutil.copy2(archive_path, staged_exe)
            _replace_file(staged_exe, target_exe, token)
        else:
            _safe_extract(archive_path, staging)
            payload = _find_payload_root(staging)
            if update_mode == UPDATE_MODE_ONEFILE:
                _replace_file(
                    _find_payload_executable(payload),
                    target_exe,
                    token,
                )
            else:
                _replace_directory(payload, target_dir, token)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    if restart:
        subprocess.Popen(
            [str(target_exe)],
            cwd=str(target_dir),
            close_fds=True,
            creationflags=_creation_flags(),
        )


def _link_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def cleanup_update_runners(target_dir: Path) -> None:
    """Remove temporary self-update copies left by previous updates."""
    target_dir = Path(target_dir).resolve()
    for root in target_dir.parent.glob(
        f".{target_dir.name}.runner-*"
    ):
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)


def prepare_update_runner(
    target_dir: Path,
    mode: str | None = None,
) -> Path:
    """Copy the executable needed to install an update after restart."""
    target_dir = Path(target_dir).resolve()
    update_mode = _normalize_update_mode(mode) or _detect_update_mode(
        target_dir
    )
    current_exe = Path(sys.executable).resolve()

    cleanup_update_runners(target_dir)
    runner_root = (
        target_dir.parent
        / f".{target_dir.name}.runner-{uuid.uuid4().hex}"
    )
    try:
        runner_root.mkdir(parents=True)
    except OSError:
        runner_root = _update_dir() / (
            f"{target_dir.name}.runner-{uuid.uuid4().hex}"
        )
        runner_root.mkdir(parents=True)

    try:
        runner_exe = runner_root / APP_EXE_NAME
        shutil.copy2(current_exe, runner_exe)
        if update_mode == UPDATE_MODE_ONEDIR:
            internal_dir = Path(
                getattr(sys, "_MEIPASS", current_exe.parent / "_internal")
            ).resolve()
            if not internal_dir.is_dir():
                raise UpdateError("当前版本缺少 onedir 运行文件")
            shutil.copytree(
                internal_dir,
                runner_root / "_internal",
                copy_function=_link_or_copy,
            )
        return runner_exe
    except OSError as exc:
        shutil.rmtree(runner_root, ignore_errors=True)
        raise UpdateError(f"无法创建内置更新副本: {exc}") from exc


def run_update_helper(argv: list[str] | None = None) -> int:
    """Run the built-in installer mode used by the temporary self-copy."""
    args = list(sys.argv if argv is None else argv)
    if len(args) not in (6, 7, 8) or args[1] != "--apply-update":
        return 2

    try:
        archive_path = Path(args[2])
        target_dir = Path(args[3])
        parent_pid = int(args[4])
        restart = args[5] == "--restart"
        mode = args[6] if len(args) >= 7 else None
        target_exe_name = args[7] if len(args) == 8 else None
        apply_update(
            archive_path,
            target_dir,
            parent_pid,
            restart,
            mode,
            target_exe_name,
        )
        _write_update_log("内置更新完成")
        return 0
    except Exception as exc:
        _write_update_log(f"内置更新失败: {exc}")
        _show_update_error(str(exc))
        return 1


def launch_update(downloaded_archive: Path) -> Path | None:
    """Start a temporary self-copy that installs the update after exit."""
    archive = Path(downloaded_archive).resolve()
    if not archive.is_file():
        raise UpdateError("更新包不存在，请重新下载")

    if not getattr(sys, "frozen", False):
        try:
            if os.name == "nt":
                os.startfile(archive.parent)
            return None
        except OSError as exc:
            raise UpdateError(f"无法打开更新目录: {exc}") from exc

    target_exe = Path(sys.executable).resolve()
    target_dir = target_exe.parent
    mode = _detect_update_mode(target_dir)
    runner = prepare_update_runner(target_dir, mode)

    try:
        subprocess.Popen(
            [
                str(runner),
                "--apply-update",
                str(archive),
                str(target_dir),
                str(os.getpid()),
                "--restart",
                mode,
                target_exe.name,
            ],
            cwd=str(runner.parent),
            close_fds=True,
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        shutil.rmtree(runner.parent, ignore_errors=True)
        raise UpdateError(f"无法启动内置更新器: {exc}") from exc
    return runner
