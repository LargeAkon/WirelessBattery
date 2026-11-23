# -*- coding: utf-8 -*-
"""读取并解析全部 HID 报告描述符，定位电量上报通道（通用，不依赖品牌）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import hid

GENERIC_DESKTOP = 0x01
BATTERY_STRENGTH = 0x20
GENERIC_DEVICE_CONTROLS = 0x06

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0192


def _open(path: bytes):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    dec = path.decode("utf-8", "ignore") if isinstance(path, bytes) else path
    h = k32.CreateFileW(dec, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
    if h == wintypes.HANDLE(-1).value or not h:
        return None, k32
    return h, k32


def read_descriptor(path: bytes) -> bytes:
    h, k32 = _open(path)
    if not h:
        return b""
    try:
        buf = ctypes.create_string_buffer(4096)
        returned = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(wintypes.HANDLE(h),
                                 IOCTL_HID_GET_REPORT_DESCRIPTOR,
                                 None, 0, buf, 4096,
                                 ctypes.byref(returned), None)
        if not ok:
            return b""
        return buf.raw[:returned.value]
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


def parse(desc: bytes) -> list[dict]:
    """极简 HID 描述符解析：抽出所有含主项的 report 及其 usage 列表。"""
    reports: list[dict] = []
    usage_page = 0
    report_id = 0
    report_size = 0
    report_count = 0
    local_usages: list[tuple[int, int]] = []
    usage_min = usage_max = None
    bit_offset_by_id: dict[tuple[int, int], int] = {}
    i = 0
    n = len(desc)
    while i < n:
        prefix = desc[i]
        if prefix == 0xFE:  # long item
            size = desc[i + 1] if i + 1 < n else 0
            i += 3 + size
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        itype = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        data = desc[i + 1:i + 1 + size]
        i += 1 + size
        value = int.from_bytes(data, "little") if data else 0

        if itype == 1:  # global
            if tag == 0:
                usage_page = value
            elif tag == 7:
                report_size = value
            elif tag == 8:
                report_id = value
            elif tag == 9:
                report_count = value
            continue
        if itype == 2:  # local
            if tag == 0:
                if size == 4:
                    local_usages.append((value & 0xFFFF, value >> 16))
                else:
                    local_usages.append((usage_page, value))
            elif tag == 1:
                usage_min = value
            elif tag == 2:
                usage_max = value
            continue

        # 主项
        if tag in (0x8, 0x9, 0xB):  # Input / Output / Feature
            kind = {0x8: "in", 0x9: "out", 0xB: "feat"}[tag]
            key = (report_id, {"in": 0, "out": 1, "feat": 2}[kind])
            offset = bit_offset_by_id.get(key, 0)
            bit_offset_by_id[key] = offset + report_size * report_count
            if local_usages:
                for page, use in local_usages:
                    if page in (GENERIC_DESKTOP, GENERIC_DEVICE_CONTROLS) and use in (
                        BATTERY_STRENGTH, 0x21, 0x22):
                        reports.append({
                            "kind": kind, "report_id": report_id,
                            "page": page, "usage": use,
                            "bit_offset": offset, "report_size": report_size,
                            "count": report_count,
                        })
            elif usage_min is not None and usage_max is not None:
                if usage_page in (GENERIC_DESKTOP, GENERIC_DEVICE_CONTROLS):
                    if usage_min <= BATTERY_STRENGTH <= usage_max:
                        reports.append({
                            "kind": kind, "report_id": report_id,
                            "page": usage_page, "usage": BATTERY_STRENGTH,
                            "bit_offset": offset, "report_size": report_size,
                            "count": report_count,
                        })
            local_usages = []
            usage_min = usage_max = None
        elif tag == 0xA or tag == 0xC:  # Collection / EndCollection
            local_usages = []
            usage_min = usage_max = None
    return reports


def main() -> int:
    seen = set()
    for info in hid.enumerate():
        path = info.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        product = (info.get("product_string") or "").strip()
        mfr = (info.get("manufacturer_string") or "").strip()
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        up = info.get("usage_page") or 0
        u = info.get("usage") or 0
        desc = read_descriptor(path)
        hits = parse(desc) if desc else []
        line = (f"{vid:04X}:{pid:04X} up={up:04X} u={u:04X} "
                f"desc={len(desc)}B {mfr} / {product}")
        print(line)
        for h in hits:
            print(f"    ★ 电量项 {h}")
        if not desc:
            print("    (无法读取描述符)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
