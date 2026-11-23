# -*- coding: utf-8 -*-
"""HID 路径上的小工具：区分蓝牙、取出同一只接收器的实例号。"""
from __future__ import annotations


def path_text(path) -> str:
    if isinstance(path, bytes):
        return path.decode("utf-8", "ignore")
    return str(path or "")


def is_bluetooth(path) -> bool:
    text = path_text(path).upper()
    return "BTHENUM" in text or "BTHLE" in text or "BTHHFENUM" in text


def phys_token(path) -> str:
    """同一只物理接收器的稳定片段。

    Windows HID 路径形如
    ``\\\\?\\HID#VID_046D&PID_C52B&MI_02#7&2a3b&0&0000#{...}``。
    中间那段在两只相同型号的接收器上不同，接口号则经常一样。
    """
    text = path_text(path)
    parts = text.split("#")
    if len(parts) >= 3:
        return parts[2].split("{")[0]
    return text
