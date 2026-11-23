# -*- coding: utf-8 -*-
"""验证 VGN / VXE / ATK 键盘（Evision 方案）电量查询：输出报文 04 + 命令 1A。"""
from __future__ import annotations

import time

import hid

VID, PID = 0x320F, 0x5088


def endpoints() -> list[dict]:
    out, seen = [], set()
    for info in hid.enumerate():
        if (info.get("vendor_id"), info.get("product_id")) != (VID, PID):
            continue
        if info.get("path") in seen:
            continue
        seen.add(info.get("path"))
        out.append(info)
    return out


def try_endpoint(info: dict, cmd: bytes, mode: str = "write") -> None:
    dev = hid.device()
    try:
        dev.open_path(info["path"])
    except Exception as exc:
        print(f"  打开失败 {info.get('usage_page'):04X}: {exc}")
        return
    try:
        dev.set_nonblocking(True)
        payload = list(cmd) + [0] * (63 - len(cmd))
        if mode == "write":
            n = dev.write([0x04] + payload)
        else:
            n = dev.send_feature_report([0x04] + payload)
        packets = []
        deadline = time.monotonic() + 0.9
        while time.monotonic() < deadline:
            data = dev.read(64)
            if data:
                packets.append(bytes(data))
            else:
                time.sleep(0.02)
        print(f"  up={info.get('usage_page'):04X} u={info.get('usage'):04X} "
              f"{mode} 写入={n}B 收到 {len(packets)} 包")
        for p in packets[:6]:
            print("      ", p[:24].hex(" "), "|", " ".join(f"{b:3d}" for b in p[:12]))
    finally:
        dev.close()


def main() -> int:
    eps = endpoints()
    print("端点:", len(eps))
    # 优先 FF1C:0092 厂商接口
    eps.sort(key=lambda i: 0 if (i.get("usage_page") == 0xFF1C) else 1)
    for cmd in (b"\x1a", b"\x1a\x00", b"\x00\x1a"):
        for mode in ("write", "feature"):
            for info in eps[:1]:
                print(f"== 命令 {cmd.hex(' ')} / {mode} / "
                      f"up={info.get('usage_page'):04X}")
                try_endpoint(info, cmd, mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
