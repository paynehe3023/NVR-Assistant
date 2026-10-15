from __future__ import annotations

import csv
import ipaddress
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from nvr_app.services.isapi_compat import (
    INPUT_PROXY_CONFIG_PATH,
    INPUT_PROXY_STATUS_PATH,
    IsapiCancelled,
    fetch_device_name,
    request_isapi,
)


ISAPI_CONFIG_PATH = INPUT_PROXY_CONFIG_PATH
ISAPI_STATUS_PATH = INPUT_PROXY_STATUS_PATH
REPORT_FIELDS = [
    "所属NVR",
    "监控设备名称",
    "IP地址",
    "通道属性",
    "对应/异常通道",
    "状态",
]
_NVR_SPLIT_PATTERN = re.compile(r"[\s,，;；]+")

NVR_FIELD_ALIASES = {
    "ip": {
        "ip",
        "ipaddress",
        "ipaddr",
        "nvr地址",
        "nvr ip",
        "管理地址",
        "设备地址",
        "地址",
    },
    "username": {
        "username",
        "user",
        "账号",
        "用户名",
        "登录用户",
        "登录用户名",
    },
    "password": {
        "password",
        "passwd",
        "pwd",
        "密码",
        "登录密码",
    },
    "name": {
        "name",
        "alias",
        "nvrname",
        "nvr名称",
        "nvr名字",
        "设备名称",
        "名称",
    },
}


class ScanCancelled(Exception):
    """NVR scan was cancelled by the user."""


def _emit_progress(callback, **event) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _node_text(node, names):
    for child in node.iter():
        if _local_name(child.tag) in names and child.text:
            value = child.text.strip()
            if value:
                return value
    return ""


def _node_texts(node, names):
    values = []
    for child in node.iter():
        if _local_name(child.tag) in names and child.text:
            value = child.text.strip()
            if value and value not in values:
                values.append(value)
    return values


def _valid_ips(values):
    result = []
    for value in values:
        value = value.strip()
        if value and value != "0.0.0.0" and value not in result:
            result.append(value)
    return result


def _normalize_key(key: str) -> str:
    return (
        (key or "")
        .lstrip("\ufeff")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def _canonical_nvr_row(row: dict) -> dict:
    normalized = {
        _normalize_key(key): str(value or "").strip()
        for key, value in row.items()
        if key
    }
    result = {}
    for field, aliases in NVR_FIELD_ALIASES.items():
        for alias in aliases:
            value = normalized.get(_normalize_key(alias), "")
            if value:
                result[field] = value
                break
    return result


def _nvr_value(nvr: dict, field: str) -> str:
    aliases = NVR_FIELD_ALIASES[field]
    for alias in aliases:
        value = nvr.get(alias)
        if value is None:
            value = nvr.get(_normalize_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_nvr_ip_text(text: str) -> list[str]:
    """Parse one or more NVR management addresses from free-form text."""
    values = []
    for value in _NVR_SPLIT_PATTERN.split(str(text or "").strip()):
        value = value.strip()
        if not value:
            continue
        try:
            normalized = str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ValueError(f"NVR 管理地址格式不正确: {value}") from exc
        if normalized not in values:
            values.append(normalized)
    return values


def build_manual_nvr_devices(
    nvr_ips,
    username: str = "",
    password: str = "",
    credential_devices=None,
) -> list[dict]:
    """Build scan devices for manually entered NVR addresses."""
    credentials = {}
    for device in credential_devices or []:
        device_ip = _nvr_value(device, "ip")
        if device_ip:
            credentials[device_ip] = device

    devices = []
    missing_credentials = []
    for nvr_ip in nvr_ips:
        normalized = str(ipaddress.ip_address(str(nvr_ip).strip()))
        credential = credentials.get(normalized, {})
        resolved_username = str(username or "").strip() or _nvr_value(
            credential,
            "username",
        )
        resolved_password = str(password or "").strip() or _nvr_value(
            credential,
            "password",
        )
        if not resolved_username or not resolved_password:
            missing_credentials.append(normalized)

        devices.append(
            {
                "ip": normalized,
                "username": resolved_username,
                "password": resolved_password,
                "name": _nvr_value(credential, "name") or f"NVR {normalized}",
            }
        )

    if missing_credentials:
        missing = "、".join(missing_credentials)
        raise ValueError(
            f"以下 NVR 缺少登录用户名或密码：{missing}。"
            "请填写手动凭据，或使用包含凭据的 NVR CSV。"
        )
    return devices


def load_nvr_devices(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"找不到 NVR 设备清单: {csv_path}")

    devices = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            clean_row = _canonical_nvr_row(row)
            if clean_row.get("ip"):
                devices.append(clean_row)
    if not devices:
        raise ValueError("NVR 设备清单中没有有效设备")
    return devices


def validate_nvr_device(nvr: dict) -> str:
    missing = [
        field
        for field in ("ip", "username", "password")
        if not _nvr_value(nvr, field)
    ]
    if missing:
        return f"NVR 配置缺少字段: {', '.join(missing)}"
    return ""


def parse_channel_config(xml_content) -> dict[str, dict]:
    root = ET.fromstring(xml_content)
    channels = {}
    for node in root.iter():
        if _local_name(node.tag) != "InputProxyChannel":
            continue
        channel_id = _node_text(node, {"id"})
        if not channel_id:
            continue
        channels[channel_id] = {
            "id": channel_id,
            "name": _node_text(node, {"name", "deviceName"}) or f"Camera {channel_id}",
            "ips": _valid_ips(_node_texts(node, {"ipAddress"})),
            "serial_number": _node_text(node, {"serialNumber"}),
            "online": None,
        }
    return channels


def parse_channel_status(xml_content) -> dict[str, dict]:
    root = ET.fromstring(xml_content)
    channels = {}
    for node in root.iter():
        if _local_name(node.tag) != "InputProxyChannelStatus":
            continue
        channel_id = _node_text(node, {"id"})
        if not channel_id:
            continue

        online_text = _node_text(node, {"online"}).lower()
        status_text = _node_text(node, {"status"}).lower()
        if online_text in {"true", "1", "online", "yes"}:
            online = True
        elif online_text in {"false", "0", "offline", "no"}:
            online = False
        elif status_text == "online":
            online = True
        elif status_text in {"offline", "disconnected"}:
            online = False
        else:
            online = None

        channels[channel_id] = {
            "id": channel_id,
            "name": _node_text(node, {"name", "deviceName"}) or f"Camera {channel_id}",
            "ips": _valid_ips(_node_texts(node, {"ipAddress"})),
            "serial_number": _node_text(node, {"serialNumber"}),
            "online": online,
        }
    return channels


def _merge_channels(channels: dict, incoming: dict) -> None:
    current = channels.get(incoming["id"])
    if current is None:
        channels[incoming["id"]] = incoming
        return

    for ip_value in incoming["ips"]:
        if ip_value not in current["ips"]:
            current["ips"].append(ip_value)
    if incoming["name"] and (
        not current["name"] or current["name"].startswith("Camera ")
    ):
        current["name"] = incoming["name"]
    if incoming["serial_number"] and not current["serial_number"]:
        current["serial_number"] = incoming["serial_number"]
    if incoming["online"] is not None:
        current["online"] = incoming["online"]


def _base_name(name: str) -> str:
    if not name or name.lower().startswith("camera"):
        return ""
    pattern = (
        r"[-_ ]?(通道|chan|ch|镜头|码流)?\d+$|"
        r"[-_ ]?(主码流|子码流|主通道|子通道|主|子|主摄|副摄)$"
    )
    base = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
    return base if len(base) >= 2 else ""


def group_channels(nvr_ip: str, channels: list[dict]) -> tuple[list[dict], list[dict]]:
    name_to_ip = {}
    name_to_serial = {}
    for channel in channels:
        base = _base_name(channel["name"])
        if not base:
            continue
        if channel["ips"]:
            name_to_ip[base] = channel["ips"][0]
        if channel["serial_number"]:
            name_to_serial[base] = channel["serial_number"]

    physical_devices = {}
    for channel in channels:
        channel_id = channel["id"]
        name = channel["name"]
        camera_ip = channel["ips"][0] if channel["ips"] else "无IP"
        serial_number = channel["serial_number"]
        base = _base_name(name)

        if camera_ip == "无IP" and base in name_to_ip:
            camera_ip = name_to_ip[base]
        if not serial_number and base in name_to_serial:
            serial_number = name_to_serial[base]

        if camera_ip != "无IP":
            device_key = f"IP_{camera_ip}"
        elif serial_number:
            device_key = f"SN_{serial_number}"
        elif base:
            device_key = f"NAME_{base}"
        else:
            device_key = f"CHAN_{channel_id}"

        if device_key not in physical_devices:
            physical_devices[device_key] = {
                "name": name,
                "ip": camera_ip,
                "serial_number": serial_number,
                "channels": {},
            }
        elif (
            physical_devices[device_key]["ip"] == "无IP"
            and camera_ip != "无IP"
        ):
            physical_devices[device_key]["ip"] = camera_ip

        physical_devices[device_key]["channels"][f"D{channel_id}"] = {
            "name": name,
            "online": channel["online"],
        }

    rows = []
    summaries = []
    duplicate_ips = _find_duplicate_ips(channels)

    for device in physical_devices.values():
        channel_map = device["channels"]
        channel_ids = list(channel_map)
        total_channels = len(channel_ids)
        channel_type = "单通道" if total_channels == 1 else "双通道"
        online_values = [info["online"] for info in channel_map.values()]
        offline_ids = [
            channel_id
            for channel_id, info in channel_map.items()
            if info["online"] is False
        ]

        if online_values and all(value is True for value in online_values):
            status = "正常在线"
            abnormal_channels = ", ".join(channel_ids)
        elif online_values and all(value is False for value in online_values):
            status = "网络不可达"
            abnormal_channels = ", ".join(channel_ids)
        elif offline_ids:
            status = "部分不可达"
            abnormal_channels = ", ".join(offline_ids)
        else:
            status = "状态未知"
            abnormal_channels = ", ".join(channel_ids)

        rows.append(
            {
                "所属NVR": nvr_ip,
                "监控设备名称": device["name"],
                "IP地址": device["ip"],
                "通道属性": channel_type,
                "对应/异常通道": abnormal_channels,
                "状态": status,
            }
        )
        summaries.append(
            {
                "name": device["name"],
                "ip": device["ip"],
                "serial_number": device["serial_number"],
                "status": status,
                "channels": channel_ids,
            }
        )

    return rows, duplicate_ips


def _find_duplicate_ips(channels: list[dict]) -> list[dict]:
    grouped = {}
    for channel in channels:
        for camera_ip in channel["ips"]:
            grouped.setdefault(camera_ip, []).append(channel["name"])

    duplicates = []
    for camera_ip, names in grouped.items():
        unique_names = list(dict.fromkeys(names))
        if len(unique_names) > 1:
            duplicates.append({"ip": camera_ip, "names": unique_names})
    return duplicates


def scan_nvr(nvr: dict, timeout: float = 8, cancel_event=None) -> dict:
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("扫描已取消")

    nvr_ip = _nvr_value(nvr, "ip")
    nvr_name = _nvr_value(nvr, "name")
    result = {
        "nvr_ip": nvr_ip,
        "nvr_name": nvr_name,
        "rows": [],
        "duplicate_ips": [],
        "error": "",
        "counts": {
            "normal": 0,
            "partial": 0,
            "offline": 0,
            "unknown": 0,
            "physical": 0,
            "channels": 0,
        },
    }

    validation_error = validate_nvr_device(nvr)
    if validation_error:
        result["error"] = validation_error
        return result

    username = _nvr_value(nvr, "username")
    password = _nvr_value(nvr, "password")
    channels = {}
    errors = []

    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("扫描已取消")
    try:
        response = request_isapi(
            nvr_ip,
            ISAPI_CONFIG_PATH,
            username,
            password,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if response.ok:
            try:
                channels.update(parse_channel_config(response.content))
            except ET.ParseError as exc:
                errors.append(f"通道配置 XML 解析失败: {exc}")
        else:
            errors.append(f"通道配置接口：{response.error}")
    except IsapiCancelled as exc:
        raise ScanCancelled(str(exc)) from exc
    except Exception as exc:
        errors.append(f"通道配置接口异常: {exc}")

    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("扫描已取消")
    try:
        response = request_isapi(
            nvr_ip,
            ISAPI_STATUS_PATH,
            username,
            password,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if response.ok:
            try:
                for channel in parse_channel_status(response.content).values():
                    _merge_channels(channels, channel)
            except ET.ParseError as exc:
                errors.append(f"通道状态 XML 解析失败: {exc}")
        else:
            errors.append(f"通道状态接口：{response.error}")
    except IsapiCancelled as exc:
        raise ScanCancelled(str(exc)) from exc
    except Exception as exc:
        errors.append(f"通道状态接口异常: {exc}")

    if not channels:
        result["error"] = "；".join(errors) or "未发现任何通道"
        return result

    channel_list = list(channels.values())
    rows, duplicates = group_channels(nvr_ip, channel_list)
    for row in rows:
        if row["状态"] == "正常在线":
            result["counts"]["normal"] += 1
        elif row["状态"] == "部分不可达":
            result["counts"]["partial"] += 1
        elif row["状态"] == "网络不可达":
            result["counts"]["offline"] += 1
        else:
            result["counts"]["unknown"] += 1

    if not nvr_name or nvr_name.startswith("NVR "):
        try:
            resolved_name = fetch_device_name(
                nvr_ip,
                username,
                password,
                timeout=timeout,
                cancel_event=cancel_event,
            )
        except IsapiCancelled as exc:
            raise ScanCancelled(str(exc)) from exc
        if resolved_name:
            result["nvr_name"] = resolved_name

    result["rows"] = rows
    result["duplicate_ips"] = duplicates
    result["counts"]["physical"] = len(rows)
    result["counts"]["channels"] = len(channel_list)
    if errors:
        result["error"] = "；".join(errors)
    return result


def scan_nvrs(
    nvr_devices: list[dict],
    timeout: float = 8,
    max_workers: int = 4,
    progress: Callable[[dict], None] | None = None,
    cancel_event=None,
) -> dict:
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("扫描已取消")
    if not nvr_devices:
        raise ValueError("NVR 设备清单为空")

    total = len(nvr_devices)
    worker_count = max(1, min(int(max_workers), total))
    completed = 0
    cancelled = False
    results = {}
    device_iterator = iter(enumerate(nvr_devices))

    def submit_next(executor, pending):
        try:
            index, nvr = next(device_iterator)
        except StopIteration:
            return
        nvr_ip = _nvr_value(nvr, "ip")
        _emit_progress(
            progress,
            phase="querying",
            message=f"正在扫描 NVR {nvr_ip}",
            nvr_ip=nvr_ip,
            completed=completed,
            total=total,
        )
        future = executor.submit(scan_nvr, nvr, timeout, cancel_event)
        pending[future] = (index, nvr)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending = {}
        for _ in range(worker_count):
            submit_next(executor, pending)

        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index, nvr = pending.pop(future)
                nvr_ip = _nvr_value(nvr, "ip")
                try:
                    result = future.result()
                except ScanCancelled:
                    cancelled = True
                    result = None
                except Exception as exc:
                    result = {
                        "nvr_ip": nvr_ip,
                        "nvr_name": _nvr_value(nvr, "name"),
                        "rows": [],
                        "duplicate_ips": [],
                        "error": str(exc),
                        "counts": {
                            "normal": 0,
                            "partial": 0,
                            "offline": 0,
                            "unknown": 0,
                            "physical": 0,
                            "channels": 0,
                        },
                    }

                if result is not None:
                    results[index] = result
                completed += 1
                _emit_progress(
                    progress,
                    phase="nvr_done",
                    message=f"已完成 NVR {nvr_ip}",
                    nvr_ip=nvr_ip,
                    completed=completed,
                    total=total,
                )

                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                elif not cancelled:
                    submit_next(executor, pending)

            if cancelled:
                for future in pending:
                    future.cancel()

    if cancelled:
        _emit_progress(
            progress,
            phase="cancelled",
            message="扫描已取消",
            completed=completed,
            total=total,
        )
        raise ScanCancelled("扫描已取消")

    ordered = [results[index] for index in range(total) if index in results]
    rows = []
    summaries = []
    failures = []
    duplicate_ips = []
    counts = {
        "normal": 0,
        "partial": 0,
        "offline": 0,
        "unknown": 0,
        "physical": 0,
        "channels": 0,
    }

    for result in ordered:
        rows.extend(result["rows"])
        duplicate_ips.extend(
            {
                "nvr_ip": result["nvr_ip"],
                "ip": item["ip"],
                "names": item["names"],
            }
            for item in result["duplicate_ips"]
        )
        for key in counts:
            counts[key] += result["counts"].get(key, 0)

        summaries.append(
            {
                "NVR地址": result["nvr_ip"],
                "NVR名称": result["nvr_name"],
                "状态": "异常" if result["error"] else "正常",
                "物理设备": result["counts"]["physical"],
                "正常在线": result["counts"]["normal"],
                "部分不可达": result["counts"]["partial"],
                "完全离线": result["counts"]["offline"],
                "状态未知": result["counts"]["unknown"],
                "通道数": result["counts"]["channels"],
                "错误": result["error"],
            }
        )
        if result["error"]:
            failures.append(
                {
                    "nvr_ip": result["nvr_ip"],
                    "nvr_name": result["nvr_name"],
                    "error": result["error"],
                }
            )

    payload = {
        "rows": rows,
        "summaries": summaries,
        "failures": failures,
        "duplicate_ips": duplicate_ips,
        "counts": counts,
        "checked_nvr_count": total,
    }
    _emit_progress(
        progress,
        phase="finished",
        message="扫描完成",
        completed=total,
        total=total,
    )
    return payload

