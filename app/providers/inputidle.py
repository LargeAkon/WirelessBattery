# -*- coding: utf-8 -*-
"""系统空闲时间：发厂商命令帧之前确认用户没在打字。

2.4G 键盘的厂商命令与按键报文同一条信道，按键中途插一帧会把 key-up 挤丢，
表现就是"t"变成"ttttt"。发送前要求系统空闲 0.3 秒即可（打字间隙足够），
用户一直不停手时最多等 1.2 秒，不无限拖。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float | None:
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    # GetTickCount 32 位，49 天回绕，所以取 GetTickCount64 的低 32 位对齐
    tick = ctypes.windll.kernel32.GetTickCount64() & 0xFFFFFFFF
    return max(0.0, ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0)


def wait_idle(need: float = 0.3, limit: float = 1.2) -> bool:
    """等到空闲 >= need 秒；超过 limit 秒就不再等，返回是否等到。"""
    deadline = time.monotonic() + limit
    while True:
        gap = idle_seconds()
        if gap is None or gap >= need:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
