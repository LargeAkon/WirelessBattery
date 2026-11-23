# -*- coding: utf-8 -*-
"""通道三：Windows 设备电量属性（直接调用 SetupAPI，毫秒级）。

读取 DEVPKEY_Device_BatteryLevel 一类属性。本工具只管 2.4G / USB 外设，
蓝牙设备（BTHENUM / BTHLE）一律不探测、不显示。
"""
from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

from model import Device, MOUSE, KEYBOARD, HEADSET, UNKNOWN

BATTERY_FMTID = (0x104EA319, 0x6EE2, 0x4701, (0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5))
BATTERY_PIDS = {2, 3, 4}

SPDRP_DEVICEDESC = 0x00000000
SPDRP_CLASS = 0x00000007
SPDRP_FRIENDLYNAME = 0x0000000C

DIGCF_PRESENT = 0x00000002
DIGCF_ALLCLASSES = 0x00000004

DEVPROP_TYPE_BYTE = 0x00000003
DEVPROP_TYPE_UINT16 = 0x00000005
DEVPROP_TYPE_UINT32 = 0x00000007
DEVPROP_TYPE_STRING = 0x00000012


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


def _load():
    api = ctypes.WinDLL("setupapi", use_last_error=True)
    api.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    api.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    api.SetupDiEnumDeviceInfo.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
    api.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
    api.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    api.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
    api.SetupDiGetDeviceRegistryPropertyW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    api.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    api.SetupDiGetDevicePropertyKeys.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(DEVPROPKEY),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    api.SetupDiGetDevicePropertyKeys.restype = wintypes.BOOL
    api.SetupDiGetDevicePropertyW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(DEVPROPKEY),
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    api.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
    api.SetupDiGetDeviceInstanceIdW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
    return api


def _instance_id(api, hdev, devinfo) -> str:
    buf = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD()
    ok = api.SetupDiGetDeviceInstanceIdW(
        hdev, ctypes.byref(devinfo), buf, ctypes.sizeof(buf), ctypes.byref(needed))
    return buf.value if ok else ""


def _reg_prop(api, hdev, devinfo, prop: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD()
    regtype = wintypes.DWORD()
    ok = api.SetupDiGetDeviceRegistryPropertyW(
        hdev, ctypes.byref(devinfo), prop, ctypes.byref(regtype),
        buf, ctypes.sizeof(buf), ctypes.byref(needed))
    return buf.value if ok else ""


def _battery_keys(api, hdev, devinfo) -> list[DEVPROPKEY]:
    count = wintypes.DWORD()
    api.SetupDiGetDevicePropertyKeys(hdev, ctypes.byref(devinfo), None, 0,
                                     ctypes.byref(count), 0)
    if count.value == 0:
        return []
    arr = (DEVPROPKEY * count.value)()
    if not api.SetupDiGetDevicePropertyKeys(hdev, ctypes.byref(devinfo), arr,
                                            count.value, ctypes.byref(count), 0):
        return []
    result = []
    for i in range(count.value):
        key = arr[i]
        fmt = key.fmtid
        if (fmt.Data1 == BATTERY_FMTID[0] and fmt.Data2 == BATTERY_FMTID[1]
                and fmt.Data3 == BATTERY_FMTID[2]):
            result.append(key)
    return result


def _read_value(api, hdev, devinfo, key: DEVPROPKEY):
    ptype = wintypes.DWORD()
    buf = ctypes.create_string_buffer(64)
    needed = wintypes.DWORD()
    ok = api.SetupDiGetDevicePropertyW(
        hdev, ctypes.byref(devinfo), ctypes.byref(key), ctypes.byref(ptype),
        buf, ctypes.sizeof(buf), ctypes.byref(needed), 0)
    if not ok:
        return None
    if ptype.value == DEVPROP_TYPE_BYTE:
        return buf.raw[0]
    if ptype.value == DEVPROP_TYPE_UINT16:
        return int.from_bytes(buf.raw[:2], "little")
    if ptype.value == DEVPROP_TYPE_UINT32:
        return int.from_bytes(buf.raw[:4], "little")
    return None


def _classify(name: str, cls: str) -> str:
    n = (name or "").lower()
    c = (cls or "").lower()
    if c == "mouse" or any(k in n for k in ("mouse", "鼠标")):
        return MOUSE
    if c == "keyboard" or any(k in n for k in ("keyboard", "键盘", "keys")):
        return KEYBOARD
    if any(k in n for k in ("headset", "headphone", "buds", "earbud", "airpods",
                            "wh-", "wf-", "耳机", "耳麦")):
        return HEADSET
    if c == "audioendpoint":
        return HEADSET
    return UNKNOWN


# 只认外设总线：ACPI/ROOT 开头的是笔记本电池、UPS，BTH* 是蓝牙，都不属于
# 本工具的监测范围（只做 2.4G / USB 有线）
_ALLOWED_PREFIX = ("HID\\", "USB\\")


def _parse_vid_pid(text: str) -> str:
    m = re.search(r"VID_([0-9A-Fa-f]{4}).{0,4}PID_([0-9A-Fa-f]{4})", text or "")
    return f"{m.group(1).upper()}:{m.group(2).upper()}" if m else ""


def scan_windows_battery(debug: list | None = None) -> list[Device]:
    try:
        api = _load()
    except Exception as exc:
        if debug is not None:
            debug.append(f"[系统] SetupAPI 加载失败: {exc}")
        return []

    hdev = api.SetupDiGetClassDevsW(None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if hdev in (None, -1, 0xFFFFFFFFFFFFFFFF):
        if debug is not None:
            debug.append("[系统] 无法枚举设备信息集")
        return []

    devices: list[Device] = []
    try:
        index = 0
        while True:
            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not api.SetupDiEnumDeviceInfo(hdev, index, ctypes.byref(devinfo)):
                break
            index += 1

            keys = _battery_keys(api, hdev, devinfo)
            if not keys:
                continue
            level = None
            for key in keys:
                if key.pid in BATTERY_PIDS:
                    value = _read_value(api, hdev, devinfo, key)
                    if value is not None and 0 <= value <= 100:
                        level = float(value)
                        break
            if level is None:
                continue

            name = (_reg_prop(api, hdev, devinfo, SPDRP_FRIENDLYNAME)
                    or _reg_prop(api, hdev, devinfo, SPDRP_DEVICEDESC))
            cls = _reg_prop(api, hdev, devinfo, SPDRP_CLASS)
            if not name:
                continue
            instance = _instance_id(api, hdev, devinfo)
            if not instance.upper().startswith(_ALLOWED_PREFIX):
                # ACPI / ROOT 开头：笔记本电池、UPS，不是无线外设
                continue
            kind = _classify(name, cls)
            devices.append(Device(
                key=f"pnp:{instance or name}",
                name=name,
                kind=kind,
                level=level,
                source="系统设备电量",
                transport="2.4G 接收器",
                raw={"instance": instance},
                vid_pid=_parse_vid_pid(instance),
            ))
    finally:
        api.SetupDiDestroyDeviceInfoList(hdev)

    if debug is not None:
        debug.append(f"[系统] 命中 {len(devices)} 个带电量设备")
    return devices
