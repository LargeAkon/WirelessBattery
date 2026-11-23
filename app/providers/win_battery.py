# -*- coding: utf-8 -*-
"""通道：Windows 电池类设备（通用层，不认品牌）。

为什么这条值得留着：部分 2.4G 接收器会把 HID 电池集合注册成 Windows 的
GUID_DEVCLASS_BATTERY 设备，这种设备不依赖厂商私有协议，换了品牌也能读。
凡是走 USB / HID 总线、且系统能给出电量的，这里都能拿到。

读取全程只读 IOCTL：
    IOCTL_BATTERY_QUERY_TAG          取本次电量标签（0 = 该设备没有电池）
    IOCTL_BATTERY_QUERY_INFORMATION  取满电容量
    IOCTL_BATTERY_QUERY_STATUS       取剩余容量与充放电状态
百分比 = 剩余容量 / 满电容量。

不写任何寄存器、不打开 HID 端点，对设备零影响。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from model import Device, MOUSE, KEYBOARD, HEADSET, UNKNOWN

# ---- 设备接口 ----
BATTERY_GUID = (0x72631E54, 0x78A4, 0x11D0,
                (0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010

SPDRP_DEVICEDESC = 0x00000000
SPDRP_FRIENDLYNAME = 0x0000000C

# ---- 文件访问 ----
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# ---- IOCTL ----
FILE_DEVICE_BATTERY = 0x29
METHOD_BUFFERED = 0
FILE_READ_ACCESS = 1


def _ctl(function: int) -> int:
    return ((FILE_DEVICE_BATTERY << 16) | (FILE_READ_ACCESS << 14)
            | (function << 2) | METHOD_BUFFERED)


IOCTL_BATTERY_QUERY_TAG = _ctl(0x10)
IOCTL_BATTERY_QUERY_INFORMATION = _ctl(0x11)
IOCTL_BATTERY_QUERY_STATUS = _ctl(0x13)

BATTERY_UNKNOWN_CAPACITY = 0xFFFFFFFF
BATTERY_POWER_ON_LINE = 0x00000001
BATTERY_DISCHARGING = 0x00000002
BATTERY_CHARGING = 0x00000004

# 只认 USB 有线 / 2.4G 接收器这两条总线。
# ACPI/ROOT 是笔记本电池、UPS；BTHENUM/BTHLE 是蓝牙 —— 本工具只管 2.4G，
# 蓝牙设备既不探测也不显示，所以一并挡掉。
_ALLOWED_PREFIX = ("HID\\", "USB\\")


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class BATTERY_QUERY_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BatteryTag", wintypes.ULONG),
        ("InformationLevel", wintypes.ULONG),
        ("AtRate", wintypes.LONG),
    ]


class BATTERY_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Capabilities", wintypes.ULONG),
        ("Technology", ctypes.c_ubyte),
        ("Reserved1", ctypes.c_ubyte * 3),
        ("Chemistry", ctypes.c_ubyte * 4),
        ("DesignedCapacity", wintypes.ULONG),
        ("FullChargedCapacity", wintypes.ULONG),
        ("DefaultAlert1", wintypes.ULONG),
        ("DefaultAlert2", wintypes.ULONG),
        ("CriticalBias", wintypes.ULONG),
        ("CycleCount", wintypes.ULONG),
    ]


class BATTERY_WAIT_STATUS(ctypes.Structure):
    _fields_ = [
        ("BatteryTag", wintypes.ULONG),
        ("Timeout", wintypes.ULONG),
        ("PowerState", wintypes.ULONG),
        ("LowCapacity", wintypes.ULONG),
        ("HighCapacity", wintypes.ULONG),
    ]


class BATTERY_STATUS(ctypes.Structure):
    _fields_ = [
        ("PowerState", wintypes.ULONG),
        ("Capacity", wintypes.ULONG),
        ("Voltage", wintypes.ULONG),
        ("Rate", wintypes.LONG),
    ]


# 64 位下 SP_DEVICE_INTERFACE_DETAIL_DATA_W 的 cbSize 是 8（4 字节 DWORD + 对齐），
# 32 位是 5。填错这一步整个枚举会返回 ERROR_INVALID_USER_BUFFER。
_DETAIL_SIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
_PATH_OFFSET = 4


def _load():
    api = ctypes.WinDLL("setupapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    api.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    api.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    api.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(GUID),
        wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    api.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    api.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(SP_DEVINFO_DATA)]
    api.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    api.SetupDiGetDeviceRegistryPropertyW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    api.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    api.SetupDiGetDeviceInstanceIdW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
    api.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    api.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return api, k32


def _guid() -> GUID:
    return GUID(BATTERY_GUID[0], BATTERY_GUID[1], BATTERY_GUID[2],
                (ctypes.c_ubyte * 8)(*BATTERY_GUID[3]))


def _reg_prop(api, hdev, devinfo, prop: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD()
    regtype = wintypes.DWORD()
    ok = api.SetupDiGetDeviceRegistryPropertyW(
        hdev, ctypes.byref(devinfo), prop, ctypes.byref(regtype),
        buf, ctypes.sizeof(buf), ctypes.byref(needed))
    return buf.value if ok else ""


def _instance_id(api, hdev, devinfo) -> str:
    buf = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD()
    ok = api.SetupDiGetDeviceInstanceIdW(
        hdev, ctypes.byref(devinfo), buf, ctypes.sizeof(buf), ctypes.byref(needed))
    return buf.value if ok else ""


def _parse_vid_pid(text: str) -> str:
    """从实例 ID 里抠出 046D:C547，用于和厂商通道交叉去重。"""
    import re

    m = re.search(r"VID_([0-9A-Fa-f]{4}).{0,4}PID_([0-9A-Fa-f]{4})", text or "")
    if m:
        return f"{m.group(1).upper()}:{m.group(2).upper()}"
    return ""


def _open_device(k32, path: str):
    """电池设备的 IOCTL 需要读写权限；个别驱动只要读，失败再退一档。"""
    share = FILE_SHARE_READ | FILE_SHARE_WRITE
    for access in (GENERIC_READ | GENERIC_WRITE, GENERIC_READ):
        handle = k32.CreateFileW(path, access, share, None, OPEN_EXISTING, 0, None)
        if handle and handle != INVALID_HANDLE_VALUE and handle != -1:
            return handle
    return None


def _read_battery(k32, path: str) -> tuple[float | None, bool, str]:
    """返回 (电量百分比, 是否充电, 状态说明)。"""
    handle = _open_device(k32, path)
    if handle is None:
        return None, False, "无法打开电池设备"

    try:
        ret = wintypes.DWORD()
        timeout = wintypes.ULONG(0)
        tag = wintypes.ULONG(0)
        if not k32.DeviceIoControl(
                handle, IOCTL_BATTERY_QUERY_TAG,
                ctypes.byref(timeout), ctypes.sizeof(timeout),
                ctypes.byref(tag), ctypes.sizeof(tag), ctypes.byref(ret), None):
            return None, False, "查询电量标签失败"
        if not tag.value:
            return None, False, "无电池"

        query = BATTERY_QUERY_INFORMATION(tag.value, 0, 0)   # 0 = BatteryInformation
        info = BATTERY_INFORMATION()
        if not k32.DeviceIoControl(
                handle, IOCTL_BATTERY_QUERY_INFORMATION,
                ctypes.byref(query), ctypes.sizeof(query),
                ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret), None):
            return None, False, "读取电池信息失败"

        full = info.FullChargedCapacity or info.DesignedCapacity
        if not full or full == BATTERY_UNKNOWN_CAPACITY:
            return None, False, "满电容量未知"

        wait = BATTERY_WAIT_STATUS(tag.value, 0, 0, 0, 0)
        status = BATTERY_STATUS()
        if not k32.DeviceIoControl(
                handle, IOCTL_BATTERY_QUERY_STATUS,
                ctypes.byref(wait), ctypes.sizeof(wait),
                ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(ret), None):
            return None, False, "读取剩余电量失败"

        if status.Capacity == BATTERY_UNKNOWN_CAPACITY:
            return None, False, "剩余电量未知"

        # 有些固件用相对容量（0-100），此时 full 也是 100，比例仍然成立
        level = status.Capacity / full * 100.0
        if level > 100.0:
            level = 100.0
        if level < 0.0:
            level = 0.0
        state = status.PowerState
        charging = bool(state & (BATTERY_CHARGING | BATTERY_POWER_ON_LINE))
        return level, charging, "正常"
    except Exception as exc:      # 结构体/驱动异常都不该让整条通道挂掉
        return None, False, f"读取异常: {exc}"
    finally:
        try:
            k32.CloseHandle(handle)
        except Exception:
            pass


def _hid_index() -> dict[tuple[int, int], tuple[str, str]]:
    """VID/PID -> (产品名, 设备类型提示)。系统电池设备的名字往往只是
    "HID-compliant mouse"，要显示成用户认得的型号就得回查 HID 枚举。"""
    from providers.hidlist import devices as hid_devices

    infos = hid_devices()

    out: dict[tuple[int, int], tuple[str, str]] = {}
    for info in infos:
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not vid:
            continue
        key = (vid, pid)
        product = (info.get("product_string") or "").strip()
        usage_page = info.get("usage_page") or 0
        usage = info.get("usage") or 0
        hint = ""
        if usage_page == 0x01 and usage == 0x06:
            hint = KEYBOARD
        elif usage_page == 0x01 and usage == 0x02:
            hint = MOUSE
        elif usage_page == 0x0C:
            hint = HEADSET
        prev_name, prev_hint = out.get(key, ("", ""))
        out[key] = (prev_name or product, prev_hint or hint)
    return out


_GENERIC = ("usb receiver", "2.4g receiver", "2.4g dongle", "wireless receiver",
            "dongle", "receiver", "hid device", "hid-compliant", "usb 输入设备",
            "usb input device")


def _looks_generic(name: str) -> bool:
    low = (name or "").lower()
    return (not low) or any(word in low for word in _GENERIC)


def _classify(name: str, hint: str) -> str:
    low = (name or "").lower()
    if any(k in low for k in ("mouse", "鼠标")):
        return MOUSE
    if any(k in low for k in ("keyboard", "键盘", "keys")):
        return KEYBOARD
    if any(k in low for k in ("headset", "headphone", "earbud", "buds", "耳机",
                              "耳麦", "wh-", "wf-")):
        return HEADSET
    return hint or UNKNOWN


def scan_win_battery(debug: list | None = None) -> list[Device]:
    try:
        api, k32 = _load()
    except Exception as exc:
        if debug is not None:
            debug.append(f"[系统电池] 加载 API 失败: {exc}")
        return []

    guid = _guid()
    hdev = api.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == INVALID_HANDLE_VALUE or hdev == -1:
        if debug is not None:
            debug.append("[系统电池] 枚举电池类设备失败")
        return []

    hid_index = _hid_index()
    devices: list[Device] = []
    enumerated = 0
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not api.SetupDiEnumDeviceInterfaces(
                    hdev, None, ctypes.byref(guid), index, ctypes.byref(iface)):
                break
            index += 1
            enumerated += 1

            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            buf = ctypes.create_string_buffer(4096)
            ctypes.memset(buf, 0, 8)
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = _DETAIL_SIZE
            needed = wintypes.DWORD()
            if not api.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(iface), buf, ctypes.sizeof(buf),
                    ctypes.byref(needed), ctypes.byref(devinfo)):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + _PATH_OFFSET)

            instance = _instance_id(api, hdev, devinfo)
            friendly = _reg_prop(api, hdev, devinfo, SPDRP_FRIENDLYNAME)
            if not instance.upper().startswith(_ALLOWED_PREFIX):
                # ACPI / ROOT 开头的是笔记本电池、UPS，不是外设。
                # 仍然记一行日志：一个都没命中时，看日志才知道是被谁挡掉的。
                if debug is not None:
                    debug.append(f"[系统电池] 跳过非外设设备 {friendly or instance}")
                continue
            level, charging, status = _read_battery(k32, path)
            vid_pid = _parse_vid_pid(instance)
            product, hint = ("", "")
            if vid_pid:
                try:
                    vid, pid = vid_pid.split(":")
                    product, hint = hid_index.get((int(vid, 16), int(pid, 16)), ("", ""))
                except Exception:
                    product = ""

            if debug is not None:
                debug.append(
                    f"[系统电池] {friendly or instance} 型号={product or '无'} "
                    f"电量={level} 充电={charging} 状态={status} "
                    f"VID:PID={vid_pid or '无'} 实例={instance}")

            if level is None:
                continue

            name = product if not _looks_generic(product) else friendly
            if _looks_generic(name):
                name = f"{product or '无线外设'} {vid_pid}".strip()

            devices.append(Device(
                key=f"winbat:{instance}",
                name=name,
                kind=_classify(name, hint),
                level=level,
                charging=charging,
                source="系统电池",
                transport="2.4G 接收器",
                raw={"state": status, "instance": instance},
                vid_pid=vid_pid,
            ))
    finally:
        api.SetupDiDestroyDeviceInfoList(hdev)

    if debug is not None:
        debug.append(
            f"[系统电池] 枚举到 {enumerated} 个电池类设备，命中 {len(devices)} 个外设"
            + ("（系统没有为这台机器的外设注册电池设备）" if enumerated == 0 else ""))
    return devices
