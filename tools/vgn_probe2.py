# -*- coding: utf-8 -*-
"""VGN VXE75 V2 电量查询深挖：多接口 / 长等待 / 唤醒后查询 / 被动监听。"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import hid

VID, PID = 0x320F, 0x5088
PAD = 0x0008  # KEYEVENTF_ 无，用 0

VK_SHIFT = 0x10


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def tap_shift() -> None:
    """按一下 Shift（不产生字符），仅用于唤醒键盘 RF 链路。"""
    for _ in range(2):
        inp = INPUT(type=1)
        inp.u.ki = KEYBDINPUT(VK_SHIFT, 0, 0, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.05)


def eps() -> list[dict]:
    out, seen = [], set()
    for info in hid.enumerate():
        if (info.get("vendor_id"), info.get("product_id")) == (VID, PID):
            if info.get("path") in seen:
                continue
            seen.add(info.get("path"))
            out.append(info)
    return out


def query(info: dict, cmd: list[int], wait: float = 2.0) -> list[bytes]:
    dev = hid.device()
    dev.open_path(info["path"])
    dev.set_nonblocking(True)
    try:
        dev.write([0x04] + cmd + [0] * (63 - len(cmd)))
        end = time.monotonic() + wait
        got = []
        while time.monotonic() < end:
            data = dev.read(64)
            if data:
                got.append(bytes(data))
            else:
                time.sleep(0.01)
        return got
    finally:
        dev.close()


def passive(info: dict, seconds: float = 8.0) -> list[bytes]:
    dev = hid.device()
    dev.open_path(info["path"])
    dev.set_nonblocking(True)
    try:
        end = time.monotonic() + seconds
        got = []
        while time.monotonic() < end:
            data = dev.read(64)
            if data:
                got.append(bytes(data))
            else:
                time.sleep(0.02)
        return got
    finally:
        dev.close()


def show(tag: str, packets: list[bytes]) -> None:
    print(f"  {tag}: {len(packets)} 包")
    for p in packets[:8]:
        print("     ", p[:16].hex(" "), "|", " ".join(f"{b:3d}" for b in p[:10]))


def main() -> int:
    all_eps = eps()
    vendor = [e for e in all_eps if (e.get("usage_page") or 0) >= 0xFF00]
    print("厂商接口:", [(f"{e.get('usage_page'):04X}:{e.get('usage'):04X}",
                        e.get("interface_number")) for e in all_eps])

    for info in vendor:
        tag = f"{info.get('usage_page'):04X}:{info.get('usage'):04X}"
        print(f"== {tag} 唤醒后查询 1A")
        tap_shift()
        time.sleep(0.25)
        show(tag + " 1A", query(info, [0x1A], 1.6))

    print("== 被动监听 8s（含 Shift 唤醒）")
    listeners = []
    for info in vendor:
        dev = hid.device()
        try:
            dev.open_path(info["path"])
            dev.set_nonblocking(True)
            listeners.append((f"{info.get('usage_page'):04X}", dev))
        except Exception:
            pass
    end = time.monotonic() + 8.0
    caught: dict[str, list[bytes]] = {}
    while time.monotonic() < end:
        if int(end - time.monotonic()) % 3 == 0:
            tap_shift()
        for name, dev in listeners:
            data = dev.read(64)
            if data:
                caught.setdefault(name, []).append(bytes(data))
        time.sleep(0.01)
    for name, dev in listeners:
        dev.close()
    for name, pkts in caught.items():
        show(name + " 被动", pkts)
    if not caught:
        print("  无主动上报")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
