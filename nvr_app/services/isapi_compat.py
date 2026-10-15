from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth


DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
INPUT_PROXY_CONFIG_PATH = "/ISAPI/ContentMgmt/InputProxy/channels"
INPUT_PROXY_STATUS_PATH = "/ISAPI/ContentMgmt/InputProxy/channels/status"
REQUEST_HEADERS = {
    "Accept": "application/xml, text/xml, */*",
    "Connection": "close",
}


class IsapiCancelled(Exception):
    """ISAPI request was cancelled by the caller."""


@dataclass(frozen=True)
class IsapiResult:
    content: bytes = b""
    status_code: int | None = None
    error_code: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _node_text(node, names):
    for child in node.iter():
        if _local_name(child.tag) in names and child.text:
            value = child.text.strip()
            if value:
                return value
    return ""


def parse_device_name(xml_content) -> str:
    try:
        root = ET.fromstring(xml_content)
    except (ET.ParseError, TypeError):
        return ""
    return _node_text(
        root,
        {
            "deviceName",
            "deviceDescription",
            "deviceType",
        },
    )


def parse_response_status_error(xml_content) -> str:
    try:
        root = ET.fromstring(xml_content)
    except (ET.ParseError, TypeError):
        return ""
    if _local_name(root.tag) != "ResponseStatus":
        return ""

    status_code = _node_text(root, {"statusCode"})
    if status_code.lower() in {"", "0", "1", "ok"}:
        return ""

    status_string = _node_text(root, {"statusString", "statusDescription"})
    sub_status_code = _node_text(root, {"subStatusCode"})
    details = [value for value in (status_string, sub_status_code) if value]
    if details:
        return f"设备返回错误 {status_code}: {' / '.join(details)}"
    return f"设备返回错误代码 {status_code}"


def _http_error(status_code: int, content: bytes) -> IsapiResult:
    response_error = parse_response_status_error(content)
    if status_code == 401:
        return IsapiResult(
            status_code=status_code,
            error_code="auth",
            error="认证失败，请检查 NVR 用户名和密码",
        )
    if status_code == 403:
        return IsapiResult(
            status_code=status_code,
            error_code="permission",
            error="账号无权访问该 ISAPI 接口",
        )
    if status_code in {404, 405, 501}:
        return IsapiResult(
            status_code=status_code,
            error_code="unsupported",
            error=f"设备不支持该 ISAPI 接口或路径不存在（HTTP {status_code}）",
        )
    if status_code >= 500:
        return IsapiResult(
            status_code=status_code,
            error_code="device",
            error=response_error or f"NVR 接口异常（HTTP {status_code}）",
        )
    return IsapiResult(
        status_code=status_code,
        error_code="http",
        error=response_error or f"ISAPI 请求失败（HTTP {status_code}）",
    )


def request_isapi(
    nvr_ip: str,
    path: str,
    username: str,
    password: str,
    timeout: float = 8,
    cancel_event=None,
) -> IsapiResult:
    """Request one ISAPI endpoint with Digest, Basic fallback and clear errors."""
    if cancel_event is not None and cancel_event.is_set():
        raise IsapiCancelled("查询已取消")

    url = f"http://{nvr_ip}{path}"
    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(username, password),
            timeout=timeout,
            headers=REQUEST_HEADERS,
        )
    except requests.Timeout:
        return IsapiResult(error_code="timeout", error="ISAPI 请求超时")
    except requests.ConnectionError:
        return IsapiResult(
            error_code="unreachable",
            error="无法连接 NVR，请检查管理地址、网络和端口",
        )
    except requests.RequestException as exc:
        return IsapiResult(
            error_code="network",
            error=f"NVR 网络请求异常: {exc}",
        )

    # Some older firmware accepts Basic authentication only.
    if response.status_code == 401:
        try:
            response = requests.get(
                url,
                auth=HTTPBasicAuth(username, password),
                timeout=timeout,
                headers=REQUEST_HEADERS,
            )
        except requests.Timeout:
            return IsapiResult(error_code="timeout", error="ISAPI 请求超时")
        except requests.ConnectionError:
            return IsapiResult(
                error_code="unreachable",
                error="无法连接 NVR，请检查管理地址、网络和端口",
            )
        except requests.RequestException as exc:
            return IsapiResult(
                error_code="network",
                error=f"NVR 网络请求异常: {exc}",
            )

    if cancel_event is not None and cancel_event.is_set():
        raise IsapiCancelled("查询已取消")

    if response.status_code != 200:
        return _http_error(response.status_code, response.content)

    response_error = parse_response_status_error(response.content)
    if response_error:
        return IsapiResult(
            status_code=response.status_code,
            error_code="device",
            error=response_error,
        )
    return IsapiResult(content=response.content, status_code=response.status_code)


def fetch_device_name(
    nvr_ip: str,
    username: str,
    password: str,
    timeout: float = 8,
    cancel_event=None,
) -> str:
    result = request_isapi(
        nvr_ip,
        DEVICE_INFO_PATH,
        username,
        password,
        timeout=timeout,
        cancel_event=cancel_event,
    )
    if not result.ok:
        return ""
    return parse_device_name(result.content)
