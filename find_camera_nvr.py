# -*- coding: utf-8 -*-
"""命令行入口：通过摄像头 IP 反查所属 NVR。"""

import argparse
import json
import sys

from camera_lookup import (
    DEFAULT_NVR_CSV,
    lookup_camera_ip,
    lookup_cameras_from_csv,
)


def _status_text(online):
    if online is True:
        return "在线"
    if online is False:
        return "离线"
    return "未知"


def _print_text_result(payload):
    if "results" in payload:
        for index, result in enumerate(payload["results"]):
            if index:
                print()
            _print_camera_result(
                result["camera_ip"],
                result["matches"],
                result.get("status", ""),
            )
    else:
        _print_camera_result(
            payload["camera_ip"],
            payload["matches"],
            payload.get("status", ""),
        )

    if payload["failed_nvrs"]:
        print("未完成查询的录像机：")
        for item in payload["failed_nvrs"]:
            print(f"- {item['nvr_ip']}: {item['error']}")


def _print_camera_result(camera_ip, matches, status=""):
    if not matches:
        if status == "query_error":
            print(f"查询摄像头 {camera_ip} 时存在 NVR 查询异常，无法确认归属。")
        else:
            print(f"未找到摄像头 {camera_ip} 对应的录像机。")
    else:
        print(f"摄像头 {camera_ip} 归属：")
        for match in matches:
            nvr_label = match["nvr_ip"]
            if match["nvr_name"]:
                nvr_label += f" ({match['nvr_name']})"
            print(
                f"- 录像机 {nvr_label} | "
                f"通道 {match['channel_id']} | "
                f"{match['channel_name']} | "
                f"{_status_text(match['online'])}"
            )


def main():
    parser = argparse.ArgumentParser(description="通过摄像头 IP 反查所属 NVR")
    parser.add_argument("camera_ip", nargs="?", help="摄像头 IP 地址；不填写时进入交互输入")
    parser.add_argument("--camera-csv", help="包含摄像头 IP 的 CSV 文件")
    parser.add_argument(
        "--nvr-csv",
        "--csv",
        dest="nvr_csv",
        default=DEFAULT_NVR_CSV,
        help="NVR 设备清单路径（需包含 NVR 的 ip、username、password）",
    )
    parser.add_argument("--timeout", type=float, default=8, help="单台 NVR 请求超时秒数")
    parser.add_argument("--workers", type=int, default=4, help="并发查询 NVR 数量")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
    args = parser.parse_args()

    if args.camera_csv and args.camera_ip:
        parser.error("不能同时提供 camera_ip 和 --camera-csv")

    try:
        if args.camera_csv:
            payload = lookup_cameras_from_csv(
                args.camera_csv,
                nvr_csv=args.nvr_csv,
                timeout=args.timeout,
                max_workers=args.workers,
            )
        else:
            camera_ip = args.camera_ip
            if not camera_ip:
                camera_ip = input("请输入摄像头 IP 地址: ").strip()
            payload = lookup_camera_ip(
                camera_ip,
                csv_path=args.nvr_csv,
                timeout=args.timeout,
                max_workers=args.workers,
            )
    except (ValueError, FileNotFoundError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"查询失败: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text_result(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
