from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
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
    zip_assets = [
        asset
        for asset in assets
        if str(asset.get("name") or "").lower().endswith(".zip")
    ]
    asset = zip_assets[0] if zip_assets else None
    if not version or not asset:
        raise UpdateError("GitHub Release 缺少版本标签或 ZIP 资产")
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
    if not name.lower().endswith(".zip"):
        name = "NVRAssistant-update.zip"
    return name


def download_update(
    url: str,
    expected_sha256: str = "",
    *,
    progress=None,
    cancel_event=None,
) -> Path:
    """Download a release ZIP and verify it before returning its path."""
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
                "已上传 ZIP，且 version.json 的 download_url 指向该文件"
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
        with ZipFile(part) as archive:
            bad_file = archive.testzip()
            if bad_file:
                raise UpdateError(f"更新包解压校验失败: {bad_file}")
    except (BadZipFile, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError("下载内容不是有效的更新 ZIP 包") from exc

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


def launch_update(downloaded_archive: Path) -> Path | None:
    """Start NVRUpdater.exe after the current process exits."""
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

    target_dir = Path(sys.executable).resolve().parent
    helper = target_dir / "NVRUpdater.exe"
    if not helper.is_file():
        raise UpdateError(
            "缺少 NVRUpdater.exe，无法自动安装。请联系维护者获取完整便携包。"
        )

    try:
        subprocess.Popen(
            [
                str(helper),
                "--apply-update",
                str(archive),
                str(target_dir),
                str(os.getpid()),
                "--restart",
            ],
            cwd=str(target_dir),
            close_fds=True,
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        raise UpdateError(f"无法启动更新助手: {exc}") from exc
    return helper
