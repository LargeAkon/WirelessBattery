# -*- coding: utf-8 -*-
"""HID 报告描述符里的电量字段。

这是给协议包用的解析工具，不是一条独立的读取通道：
报告描述符能说明每个 report ID 有多长、有没有声明 Battery Strength
（页面 0x01 / 0x06，用途 0x20）。协议包据此判断该发多长的帧、去哪个字节取值，
不再靠猜。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0192


def read_descriptor(path) -> bytes:
    text = path.decode("utf-8", "ignore") if isinstance(path, bytes) else str(path)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    k32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.CreateFileW(
        text, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if not handle or handle == wintypes.HANDLE(-1).value:
        return b""
    try:
        buf = ctypes.create_string_buffer(4096)
        returned = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(
            wintypes.HANDLE(handle), IOCTL_HID_GET_REPORT_DESCRIPTOR,
            None, 0, buf, 4096, ctypes.byref(returned), None,
        )
        if not ok:
            return b""
        return buf.raw[:returned.value]
    finally:
        k32.CloseHandle(wintypes.HANDLE(handle))


def parse_battery_fields(desc: bytes) -> list[dict]:
    """抽出描述符里的 Battery Strength 字段。"""
    fields: list[dict] = []
    if not desc:
        return fields
    usage_page = 0
    report_id = 0
    report_size = 0
    report_count = 0
    logical_max = 100
    local: list[tuple[int, int]] = []
    usage_min = usage_max = None
    offsets: dict[tuple, int] = {}
    i = 0
    n = len(desc)
    while i < n:
        prefix = desc[i]
        if prefix == 0xFE:
            size = desc[i + 1] if i + 1 < n else 0
            i += 3 + size
            continue
        size_code = prefix & 0x03
        size = (0, 1, 2, 4)[size_code]
        itype = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        data = desc[i + 1:i + 1 + size]
        i += 1 + size
        value = int.from_bytes(data, "little") if data else 0

        if itype == 1:
            if tag == 0:
                usage_page = value
            elif tag == 2:
                logical_max = value
            elif tag == 7:
                report_size = value
            elif tag == 8:
                report_id = value
            elif tag == 9:
                report_count = value
            continue
        if itype == 2:
            if tag == 0:
                if size == 4:
                    local.append((value & 0xFFFF, value >> 16))
                else:
                    local.append((usage_page, value))
            elif tag == 1:
                usage_min = value
            elif tag == 2:
                usage_max = value
            continue
        if tag not in (0x8, 0x9, 0xB):
            if tag in (0xA, 0xC):
                local = []
                usage_min = usage_max = None
            continue

        kind = {0x8: "in", 0x9: "out", 0xB: "feat"}[tag]
        key = (report_id, kind)
        offset = offsets.get(key, 0)
        width = report_size * report_count
        offsets[key] = offset + width
        usages = list(local)
        if not usages and usage_min is not None and usage_max is not None:
            if usage_page in (0x01, 0x06) and usage_min <= 0x20 <= usage_max:
                usages = [(usage_page, 0x20)]
                bit = offset + (0x20 - usage_min) * report_size
                fields.append(_field(report_id, kind, bit, report_size, logical_max))
            local = []
            usage_min = usage_max = None
            continue
        for idx, (page, use) in enumerate(usages):
            if page in (0x01, 0x06) and use == 0x20:
                fields.append(_field(
                    report_id, kind, offset + idx * report_size, report_size, logical_max,
                ))
        local = []
        usage_min = usage_max = None
    return fields


def _field(report_id: int, kind: str, bit: int, report_size: int, logical_max: int) -> dict:
    return {
        "report_id": report_id,
        "kind": kind,
        "bit_offset": bit,
        "bit_size": report_size or 8,
        "logical_max": logical_max,
    }


def extract_bits(payload: bytes, bit_offset: int, bit_size: int) -> int | None:
    if bit_size <= 0 or bit_size > 16:
        return None
    if bit_offset + bit_size > len(payload) * 8:
        return None
    value = 0
    for bit in range(bit_size):
        pos = bit_offset + bit
        if payload[pos // 8] & (1 << (pos % 8)):
            value |= 1 << bit
    return value


def to_percent(value: int | None, logical_max: int) -> float | None:
    if value is None:
        return None
    if 1 <= logical_max <= 15 and 0 <= value <= logical_max:
        return float(round(value * 100 / logical_max))
    # 量程大于 100、读数也超过 100：这是 0–255 这类满量程，不是无效值。
    # 读数本身不超过 100 时仍当作百分比，避免把已经是百分比的字段再缩一次。
    if logical_max > 100 and 100 < value <= logical_max:
        return float(round(value * 100 / logical_max))
    if 0 <= value <= 100:
        return float(value)
    return None

