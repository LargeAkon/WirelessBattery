# -*- coding: utf-8 -*-
"""系统空闲时间：发厂商命令帧之前确认用户没在打字。

2.4G 键盘的厂商命令与按键报文共用同一条空中链路（多数接收器连 HID 接口
都是同一个，只在 collection 上分家）。按键中途插一帧，key-up 会被挤到
命令往返之后 —— 用户看到的就是"按 w 半天没反应，过一会一串字冒出来"。

所以这里的规矩是**让位优先**：
    用户正在连续输入时，这一轮干脆不发帧，等下次刷新再说。

原来这里是"最多等 1.2 秒就硬发"，等于用户打字打到一半也会被插帧，
是按键延迟的直接来源之一。现在改成等不到空隙就返回 False，由调用方
放弃本轮（不记失败、不动缓存）。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

# 需要多长的输入空隙才允许插一帧。0.6 秒足够覆盖正常打字的字间停顿，
# 又短到不会让"刚停手"的用户多等。
IDLE_NEED = 0.6
# 最多为一帧等多久。超时即放弃本轮，不做"等不及就硬发"。
IDLE_LIMIT = 3.0


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


def wait_idle(need: float = IDLE_NEED, limit: float = IDLE_LIMIT) -> bool:
    """等到空闲 >= need 秒。返回 True 表示可以发帧，False 表示用户一直在输入。

    判定不了空闲（拿不到 GetLastInputInfo）时按"可以发"处理：
    这种情况极罕见，而且数据比体感更重要。
    """
    deadline = time.monotonic() + limit
    while True:
        gap = idle_seconds()
        if gap is None or gap >= need:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.03)
