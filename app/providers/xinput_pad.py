# -*- coding: utf-8 -*-
"""Xbox 协议手柄的电量。

飞智、八位堂、部分雷蛇手柄的 2.4G 接收器在系统里就是一只 Xbox 手柄，
没有自己的 HID 电量报告。XInput 只给四档，空 / 低 / 中 / 满。
有线手柄不在这里显示。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from model import Device, GAMEPAD, HEADSET

_LEVELS = {0: 5.0, 1: 25.0, 2: 60.0, 3: 100.0}
# 0 未连接，1 有线。其余才是无线电池。
_SKIP_TYPES = {0x00, 0x01}


class _BatteryInfo(ctypes.Structure):
    _fields_ = [
        ("BatteryType", ctypes.c_ubyte),
        ("BatteryLevel", ctypes.c_ubyte),
    ]


def _dll():
    for name in ("xinput1_4", "xinput1_3"):
        try:
            lib = ctypes.WinDLL(name)
        except OSError:
            continue
        fn = lib.XInputGetBatteryInformation
        fn.argtypes = [wintypes.DWORD, ctypes.c_ubyte, ctypes.POINTER(_BatteryInfo)]
        fn.restype = wintypes.DWORD
        return fn
    return None


def scan_xinput(debug: list | None = None) -> list[Device]:
    fn = _dll()
    if fn is None:
        if debug is not None:
            debug.append("[手柄] 没有 XInput")
        return []

    devices: list[Device] = []
    for slot in range(4):
        for devtype, kind, label in (
            (0x00, GAMEPAD, "无线手柄"),
            (0x01, HEADSET, "手柄耳机"),
        ):
            info = _BatteryInfo()
            if fn(slot, devtype, ctypes.byref(info)) != 0:
                continue
            if info.BatteryType in _SKIP_TYPES:
                continue
            level = _LEVELS.get(info.BatteryLevel)
            if level is None:
                continue
            name = f"{label} {slot + 1}"
            if debug is not None:
                debug.append(
                    f"[手柄] 槽位{slot + 1} {label} 类型={info.BatteryType:#x} 电量={level}"
                )
            devices.append(Device(
                key=f"xinput:{slot}:{devtype}",
                name=name,
                kind=kind,
                level=level,
                source="手柄电量",
                transport="2.4G 接收器",
                raw={"phys": f"xinput:{slot}:{devtype}", "state": "正常"},
                vid_pid="",
            ))
    if debug is not None:
        debug.append(f"[手柄] 命中 {len(devices)} 台")
    return devices
