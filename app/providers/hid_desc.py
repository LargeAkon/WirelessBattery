# -*- coding: utf-8 -*-
"""标准 HID 电量字段。

很多 2.4G 接收器不说私有协议，但报告描述符里声明了
Battery Strength（页面 0x01 / 0x06，用途 0x20）。
描述符对上才读，读到的值还要落在该字段自己的量程里。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import GAMEPAD, Device, HEADSET, KEYBOARD, MOUSE, UNKNOWN
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth, phys_token

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0192

_FIELDS: dict[bytes, list[dict]] = {}


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


def _fields_for(path: bytes) -> list[dict]:
    cached = _FIELDS.get(path)
    if cached is not None:
        return cached
    try:
        desc = read_descriptor(path)
    except Exception:
        desc = b""
    parsed = parse_battery_fields(desc)
    _FIELDS[path] = parsed
    return parsed


def _payload_after_id(data: bytes, report_id: int) -> bytes | None:
    if not data:
        return None
    if report_id:
        if data[0] != report_id:
            return None
        return data[1:]
    return data


def _read_field(dev, field: dict) -> float | None:
    report_id = field["report_id"] or 0
    if field["kind"] == "feat":
        try:
            raw = dev.get_feature_report(report_id, 64)
        except Exception:
            return None
        payload = _payload_after_id(bytes(raw or b""), report_id)
        if payload is None:
            return None
        value = extract_bits(payload, field["bit_offset"], field["bit_size"])
        return to_percent(value, field["logical_max"])

    if field["kind"] != "in":
        return None
    deadline = time.monotonic() + 0.35
    while time.monotonic() < deadline:
        try:
            raw = dev.read(64, 40)
        except Exception:
            return None
        if not raw:
            continue
        payload = _payload_after_id(bytes(raw), report_id)
        if payload is None:
            continue
        value = extract_bits(payload, field["bit_offset"], field["bit_size"])
        level = to_percent(value, field["logical_max"])
        if level is not None:
            return level
    return None


def _kind_of(usages: set[tuple[int, int]], name: str) -> str:
    low = (name or "").lower()
    if any(k in low for k in ("headset", "headphone", "earbud", "耳机", "耳麦")):
        return HEADSET
    if ((0x01, 0x05) in usages or (0x01, 0x04) in usages
            or any(k in low for k in ("controller", "gamepad", "手柄"))):
        return GAMEPAD
    if (0x01, 0x02) in usages or "mouse" in low or "鼠标" in low:
        return MOUSE
    if (0x01, 0x06) in usages or "keyboard" in low or "键盘" in low:
        return KEYBOARD
    return UNKNOWN


def _name_of(infos: list[dict], vid: int, pid: int) -> str:
    for info in infos:
        product = (info.get("product_string") or "").strip()
        if product and product not in ("-", "USB Receiver", "2.4G Receiver"):
            return product
    for info in infos:
        product = (info.get("product_string") or "").strip()
        if product:
            return f"{product} {vid:04X}:{pid:04X}"
    return f"无线设备 {vid:04X}:{pid:04X}"


def scan_hid_battery(debug: list | None = None) -> list[Device]:
    if hid is None:
        return []
    infos = hid_devices()

    groups: dict[tuple, list[dict]] = {}
    for info in infos:
        path = info.get("path")
        if not path or is_bluetooth(path):
            continue
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not vid:
            continue
        groups.setdefault((vid, pid, phys_token(path)), []).append(info)

    devices: list[Device] = []
    for (vid, pid, phys), members in groups.items():
        usages = {(i.get("usage_page") or 0, i.get("usage") or 0) for i in members}
        chosen = None
        level = None
        for info in members:
            fields = [f for f in _fields_for(info["path"]) if f["kind"] in ("feat", "in")]
            fields.sort(key=lambda f: 0 if f["kind"] == "feat" else 1)
            if not fields:
                continue
            dev = hid.device()
            try:
                dev.open_path(info["path"])
                dev.set_nonblocking(True)
            except Exception:
                continue
            try:
                for field in fields:
                    level = _read_field(dev, field)
                    if level is not None:
                        chosen = info
                        break
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            if level is not None:
                break
        if level is None or chosen is None:
            continue
        name = _name_of(members, vid, pid)
        if debug is not None:
            debug.append(f"[HID 电量] {vid:04X}:{pid:04X} {name!r} 电量={level}")
        devices.append(Device(
            key=f"hidbat:{vid:04x}:{pid:04x}:{phys}",
            name=name,
            kind=_kind_of(usages, name),
            level=level,
            source="HID 电量",
            transport="2.4G 接收器",
            raw={"phys": phys, "state": "正常"},
            vid_pid=f"{vid:04X}:{pid:04X}",
        ))
    if debug is not None:
        debug.append(f"[HID 电量] 命中 {len(devices)} 台")
    return devices
