# -*- coding: utf-8 -*-
"""通过摄像头 IP 反查所属 NVR 的共享逻辑。"""

#调用方法：py find_camera_nvr.py --camera-csv cameras.csv

import csv
import ipaddress
import os
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from nvr_app.services.isapi_compat import (
    IsapiCancelled,
    fetch_device_name,
    request_isapi,
)
from nvr_app.services.nvr_scan_service import (
    load_nvr_devices as _load_nvr_devices,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NVR_CSV = os.path.join(BASE_DIR, "NVRdevicesTest.csv")

ISAPI_CONFIG_PATH = "/ISAPI/ContentMgmt/InputProxy/channels"
ISAPI_STATUS_PATH = "/ISAPI/ContentMgmt/InputProxy/channels/status"

CAMERA_IP_FIELDS = {
    "ip",
    "ipaddress",
    "ip_address",
    "camera_ip",
    "cameraip",
    "摄像头ip",
    "摄像机ip",
    "ip地址",
    "摄像头地址",
    "摄像机地址",
}


class LookupCancelled(Exception):
    """摄像头反查任务被用户取消。"""


def _emit_progress(callback, **event):
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # 进度展示不应影响实际查询结果。
        pass


def _local_name(tag):
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
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.is_unspecified:
            continue
        normalized = str(ip)
        if normalized not in result:
            result.append(normalized)
    return result


def _online_value(node):
    online_text = _node_text(node, {"online"}).lower()
    status_text = _node_text(node, {"status"}).lower()

    if online_text in {"true", "1", "online", "yes"}:
        return True
    if online_text in {"false", "0", "offline", "no"}:
        return False
    if status_text == "online":
        return True
    if status_text in {"offline", "disconnected"}:
        return False
    return None


def parse_input_proxy_channels(xml_content):
    """解析 ISAPI 通道配置，返回 channel_id -> 通道信息。"""
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


def parse_channel_status(xml_content):
    """解析 ISAPI 通道状态，返回 channel_id -> 状态信息。"""
    root = ET.fromstring(xml_content)
    channels = {}

    for node in root.iter():
        if _local_name(node.tag) != "InputProxyChannelStatus":
            continue

        channel_id = _node_text(node, {"id"})
        if not channel_id:
            continue

        channels[channel_id] = {
            "id": channel_id,
            "name": _node_text(node, {"name", "deviceName"}) or f"Camera {channel_id}",
            "ips": _valid_ips(_node_texts(node, {"ipAddress"})),
            "serial_number": _node_text(node, {"serialNumber"}),
            "online": _online_value(node),
        }

    return channels


def load_nvr_devices(csv_path=DEFAULT_NVR_CSV):
    """读取 NVR 设备清单。"""
    return _load_nvr_devices(csv_path)


def load_camera_ips(csv_path):
    """从摄像头 CSV 中读取 IP；密码等无关列会被忽略。"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"找不到摄像头 IP 清单: {csv_path}")

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file_obj:
        rows = list(csv.reader(file_obj))

    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    ip_indexes = [
        index for index, name in enumerate(header) if name in CAMERA_IP_FIELDS
    ]

    if ip_indexes:
        data_rows = rows[1:]
    else:
        # 兼容无表头或自定义表头 CSV：扫描所有列，仅保留合法 IP。
        column_count = max(len(row) for row in rows)
        ip_indexes = list(range(column_count))
        data_rows = rows

    camera_ips = []
    for row in data_rows:
        for index in ip_indexes:
            if index >= len(row):
                continue
            try:
                normalized = str(ipaddress.ip_address(row[index].strip()))
            except (TypeError, ValueError):
                continue
            if normalized not in camera_ips:
                camera_ips.append(normalized)

    return camera_ips


def _merge_channel(channels, channel_id, incoming):
    current = channels.get(channel_id)
    if current is None:
        channels[channel_id] = incoming
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


def fetch_nvr_channels(nvr, timeout=8, cancel_event=None):
    """读取单个 NVR 的通道配置和状态。"""
    if cancel_event is not None and cancel_event.is_set():
        raise LookupCancelled("查询已取消")

    nvr_ip = nvr.get("ip", "")
    username = nvr.get("username", "")
    password = nvr.get("password", "")
    nvr_name = nvr.get("name") or nvr.get("alias") or ""

    result = {
        "nvr_ip": nvr_ip,
        "nvr_name": nvr_name,
        "channels": [],
        "error": None,
    }

    if not nvr_ip or not username or not password:
        result["error"] = "NVR 配置缺少 ip、username 或 password"
        return result

    channels = {}
    errors = []

    try:
        if cancel_event is not None and cancel_event.is_set():
            raise LookupCancelled("查询已取消")
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
                channels.update(parse_input_proxy_channels(response.content))
            except ET.ParseError as exc:
                errors.append(f"通道配置 XML 解析失败: {exc}")
        else:
            errors.append(f"通道配置接口：{response.error}")
    except IsapiCancelled as exc:
        raise LookupCancelled(str(exc)) from exc
    except LookupCancelled:
        raise
    except Exception as exc:
        errors.append(f"通道配置接口异常: {exc}")

    try:
        if cancel_event is not None and cancel_event.is_set():
            raise LookupCancelled("查询已取消")
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
                for channel_id, incoming in parse_channel_status(
                    response.content
                ).items():
                    _merge_channel(channels, channel_id, incoming)
            except ET.ParseError as exc:
                errors.append(f"通道状态 XML 解析失败: {exc}")
        else:
            errors.append(f"通道状态接口：{response.error}")
    except IsapiCancelled as exc:
        raise LookupCancelled(str(exc)) from exc
    except LookupCancelled:
        raise
    except Exception as exc:
        errors.append(f"通道状态接口异常: {exc}")

    if channels:
        result["channels"] = list(channels.values())
    else:
        result["error"] = "；".join(errors) or "未发现任何通道"

    if result["channels"] and (not nvr_name or nvr_name.startswith("NVR ")):
        try:
            resolved_name = fetch_device_name(
                nvr_ip,
                username,
                password,
                timeout=timeout,
                cancel_event=cancel_event,
            )
        except IsapiCancelled as exc:
            raise LookupCancelled(str(exc)) from exc
        except Exception:
            # 名称是补充信息，读取失败不应让通道查询整体失败。
            resolved_name = ""
        if resolved_name:
            result["nvr_name"] = resolved_name

    return result


def lookup_camera_ips(
    camera_ips,
    csv_path=DEFAULT_NVR_CSV,
    timeout=8,
    max_workers=4,
    progress=None,
    cancel_event=None,
):
    """并发查询所有 NVR，一次匹配多个摄像头 IP。"""
    if cancel_event is not None and cancel_event.is_set():
        raise LookupCancelled("查询已取消")

    normalized_ips = []
    for camera_ip in camera_ips:
        try:
            normalized_ip = str(ipaddress.ip_address(str(camera_ip).strip()))
        except ValueError as exc:
            raise ValueError(f"摄像头 IP 格式不正确: {camera_ip}") from exc
        if normalized_ip not in normalized_ips:
            normalized_ips.append(normalized_ip)

    _emit_progress(
        progress,
        phase="loading",
        message="正在读取 NVR 设备清单",
        completed=0,
        total=0,
    )
    nvr_devices = load_nvr_devices(csv_path)

    if not nvr_devices:
        _emit_progress(
            progress,
            phase="finished",
            message="NVR 设备清单为空",
            completed=0,
            total=0,
        )
        return {
            "camera_ips": normalized_ips,
            "results": [
                {"camera_ip": camera_ip, "matches": []}
                for camera_ip in normalized_ips
            ],
            "checked_nvr_count": 0,
            "failed_nvrs": [],
        }

    worker_count = max(1, min(max_workers, len(nvr_devices)))
    nvr_results = []
    completed = 0
    cancelled = False
    total = len(nvr_devices)
    device_iterator = iter(enumerate(nvr_devices))

    def submit_next(executor, pending):
        try:
            index, nvr = next(device_iterator)
        except StopIteration:
            return
        _emit_progress(
            progress,
            phase="querying",
            message=f"正在查询 NVR {nvr.get('ip', '')}",
            nvr_ip=nvr.get("ip", ""),
            completed=completed,
            total=total,
        )
        future = executor.submit(fetch_nvr_channels, nvr, timeout, cancel_event)
        pending[future] = (index, nvr)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending = {}
        for _ in range(worker_count):
            submit_next(executor, pending)

        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index, nvr = pending.pop(future)
                try:
                    result = future.result()
                except LookupCancelled:
                    cancelled = True
                    result = None
                except Exception as exc:
                    result = {
                        "nvr_ip": nvr.get("ip", ""),
                        "nvr_name": nvr.get("name") or nvr.get("alias") or "",
                        "channels": [],
                        "error": str(exc),
                    }

                if result is not None:
                    result["_input_index"] = index
                    nvr_results.append(result)

                completed += 1
                _emit_progress(
                    progress,
                    phase="nvr_done",
                    message=f"已完成 NVR {nvr.get('ip', '')}",
                    nvr_ip=nvr.get("ip", ""),
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
            message="查询已取消",
            completed=completed,
            total=total,
        )
        raise LookupCancelled("查询已取消")

    nvr_results.sort(key=lambda item: item.get("_input_index", total))
    for result in nvr_results:
        result.pop("_input_index", None)

    matches_by_ip = {camera_ip: [] for camera_ip in normalized_ips}
    failed_nvrs = []

    for nvr_result in nvr_results:
        if nvr_result["error"]:
            failed_nvrs.append({
                "nvr_ip": nvr_result["nvr_ip"],
                "nvr_name": nvr_result["nvr_name"],
                "error": nvr_result["error"],
            })

        for channel in nvr_result["channels"]:
            for camera_ip in channel["ips"]:
                if camera_ip not in matches_by_ip:
                    continue

                matches_by_ip[camera_ip].append({
                    "nvr_ip": nvr_result["nvr_ip"],
                    "nvr_name": nvr_result["nvr_name"],
                    "channel_id": channel["id"],
                    "channel_name": channel["name"],
                    "camera_ips": channel["ips"],
                    "camera_serial_number": channel["serial_number"],
                    "online": channel["online"],
                })

    results = []
    for camera_ip in normalized_ips:
        matches = matches_by_ip[camera_ip]
        if matches:
            status = "matched"
        elif failed_nvrs:
            status = "query_error"
        else:
            status = "not_found"
        results.append(
            {
                "camera_ip": camera_ip,
                "status": status,
                "matches": matches,
            }
        )

    payload = {
        "camera_ips": normalized_ips,
        "results": results,
        "checked_nvr_count": len(nvr_devices),
        "failed_nvrs": failed_nvrs,
    }
    _emit_progress(
        progress,
        phase="finished",
        message="查询完成",
        completed=total,
        total=total,
    )
    return payload


def lookup_camera_ip(
    camera_ip,
    csv_path=DEFAULT_NVR_CSV,
    timeout=8,
    max_workers=4,
    progress=None,
    cancel_event=None,
):
    """兼容单 IP 查询，返回该摄像头 IP 的归属信息。"""
    payload = lookup_camera_ips(
        [camera_ip],
        csv_path=csv_path,
        timeout=timeout,
        max_workers=max_workers,
        progress=progress,
        cancel_event=cancel_event,
    )
    result = payload["results"][0]
    return {
        "camera_ip": result["camera_ip"],
        "status": result["status"],
        "matches": result["matches"],
        "checked_nvr_count": payload["checked_nvr_count"],
        "failed_nvrs": payload["failed_nvrs"],
    }


def lookup_cameras_from_csv(
    camera_csv,
    nvr_csv=DEFAULT_NVR_CSV,
    timeout=8,
    max_workers=4,
    progress=None,
    cancel_event=None,
):
    """读取摄像头 IP CSV，并实时查询 NVR 归属。"""
    _emit_progress(
        progress,
        phase="reading_camera_csv",
        message="正在读取摄像头 CSV",
        completed=0,
        total=0,
    )
    camera_ips = load_camera_ips(camera_csv)
    if not camera_ips:
        raise ValueError("摄像头 CSV 中没有有效的 IP 地址")

    payload = lookup_camera_ips(
        camera_ips,
        csv_path=nvr_csv,
        timeout=timeout,
        max_workers=max_workers,
        progress=progress,
        cancel_event=cancel_event,
    )
    payload["camera_csv"] = os.path.abspath(camera_csv)
    return payload
