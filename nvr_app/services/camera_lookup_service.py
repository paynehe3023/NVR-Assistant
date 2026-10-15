from __future__ import annotations

import ipaddress
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from camera_lookup import (
    BASE_DIR,
    DEFAULT_NVR_CSV,
    LookupCancelled,
    load_camera_ips,
    lookup_camera_ip as _lookup_camera_ip,
    lookup_camera_ips as _lookup_camera_ips,
    lookup_cameras_from_csv as _lookup_cameras_from_csv,
)


LOOKUP_CANCELLED = LookupCancelled
_IP_SPLIT_PATTERN = re.compile(r"[\s,，;；]+")


def resolve_nvr_csv_path(preferred_path: str = "") -> str:
    """Find the NVR inventory without requiring users to select it every time."""
    candidates = []
    if preferred_path:
        candidates.append(Path(preferred_path).expanduser())

    candidates.append(Path(DEFAULT_NVR_CSV))
    roots = [
        Path(BASE_DIR),
        Path.cwd(),
        Path(sys.executable).resolve().parent,
    ]
    for root in roots:
        for name in ("NVRdevices.csv", "NVRdevicesTest.csv"):
            candidates.append(root / name)

    seen = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def parse_camera_ip_text(text: str) -> list[str]:
    """Parse one or more camera IPs from a free-form text area."""
    values = []
    for value in _IP_SPLIT_PATTERN.split(text.strip()):
        value = value.strip()
        if not value:
            continue
        try:
            normalized = str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ValueError(f"摄像头 IP 格式不正确: {value}") from exc
        if normalized not in values:
            values.append(normalized)
    return values


def normalize_camera_ips(camera_ips: Iterable[str]) -> list[str]:
    values = []
    for camera_ip in camera_ips:
        try:
            normalized = str(ipaddress.ip_address(str(camera_ip).strip()))
        except ValueError as exc:
            raise ValueError(f"摄像头 IP 格式不正确: {camera_ip}") from exc
        if normalized not in values:
            values.append(normalized)
    return values


def load_camera_ips_from_csv(csv_path: str) -> list[str]:
    return load_camera_ips(csv_path)


def lookup_camera_ip(
    camera_ip: str,
    csv_path: str,
    timeout: float = 8,
    max_workers: int = 4,
    progress=None,
    cancel_event=None,
):
    return _lookup_camera_ip(
        camera_ip,
        csv_path=csv_path,
        timeout=timeout,
        max_workers=max_workers,
        progress=progress,
        cancel_event=cancel_event,
    )


def lookup_camera_ips(
    camera_ips: Iterable[str],
    csv_path: str,
    timeout: float = 8,
    max_workers: int = 4,
    progress=None,
    cancel_event=None,
):
    return _lookup_camera_ips(
        list(camera_ips),
        csv_path=csv_path,
        timeout=timeout,
        max_workers=max_workers,
        progress=progress,
        cancel_event=cancel_event,
    )


def lookup_cameras_from_csv(
    camera_csv: str,
    nvr_csv: str,
    timeout: float = 8,
    max_workers: int = 4,
    progress=None,
    cancel_event=None,
):
    return _lookup_cameras_from_csv(
        camera_csv,
        nvr_csv=nvr_csv,
        timeout=timeout,
        max_workers=max_workers,
        progress=progress,
        cancel_event=cancel_event,
    )

