# -*- coding: utf-8 -*-
"""托盘图标在任务栏上的真实位置。

Windows 11 默认把新图标收进「显示隐藏的图标」。收进去之后，
Shell_NotifyIconGetRect 仍返回一枚图标大小的矩形，而且这个矩形就是
「^」按钮本身。悬停如果拿它当热区，鼠标停在箭头上就会把卡片弹出来。

这里做两件事：
1. 问任务栏上这个矩形中心是什么控件，是「^」就不算自己的图标；
2. 安装后的 WirelessBattery.exe 把自己标成显示在任务栏上。开发时用
   python.exe 跑不改注册表，免得把别的 Python 托盘图标也拽出来。
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

# 任务栏「^」在不同语言里的无障碍名称。只认这几个，避免误伤自己的提示文字。
_CHEVRON_EXACT = {
    "显示隐藏的图标",
    "show hidden icons",
    "notification chevron",
}

_UIA = None
_UIA_FAILED = False
_COM = None
_CACHE = {"key": None, "at": 0.0, "hit": False}
_CACHE_SEC = 2.0

_CLSID = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
_IID = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
_NAME_PROP = 30005


def is_overflow_chevron_name(name: str | None) -> bool:
    """这个无障碍名称是不是任务栏的「显示隐藏的图标」。"""
    text = (name or "").strip()
    if not text:
        return False
    low = text.lower()
    if text in _CHEVRON_EXACT or low in _CHEVRON_EXACT:
        return True
    return "隐藏的图标" in text or "hidden icons" in low


def rect_is_overflow_chevron(rect) -> bool:
    """托盘矩形的中心是不是「^」按钮。问失败时不当成是，悬停照常。"""
    if rect is None or rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        return False
    key = (int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))
    now = time.monotonic()
    if _CACHE["key"] == key and (now - _CACHE["at"]) < _CACHE_SEC:
        return bool(_CACHE["hit"])
    cx = rect.x() + rect.width() / 2.0
    cy = rect.y() + rect.height() / 2.0
    px, py = _to_physical(cx, cy)
    hit = is_overflow_chevron_name(_element_name_at(px, py))
    _CACHE["key"] = key
    _CACHE["at"] = now
    _CACHE["hit"] = hit
    return hit


def promote_own_tray_icon() -> bool:
    """让安装后的本程序图标留在任务栏上。改过注册表才返回 True。"""
    exe = Path(sys.executable)
    if exe.name.lower() != "wirelessbattery.exe":
        return False
    if sys.platform != "win32":
        return False
    import winreg

    target = str(exe).lower()
    changed = False
    try:
        root = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\NotifyIconSettings",
        )
    except OSError:
        return False
    try:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            changed = _promote_key(root, name, target) or changed
    finally:
        winreg.CloseKey(root)
    return changed


def _promote_key(root, name: str, target: str) -> bool:
    import winreg

    try:
        key = winreg.OpenKey(root, name, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
    except OSError:
        return False
    try:
        try:
            path, _ = winreg.QueryValueEx(key, "ExecutablePath")
        except OSError:
            return False
        if str(path).lower() != target:
            return False
        try:
            promoted, _ = winreg.QueryValueEx(key, "IsPromoted")
        except OSError:
            promoted = 0
        if int(promoted) == 1:
            return False
        winreg.SetValueEx(key, "IsPromoted", 0, winreg.REG_DWORD, 1)
        return True
    finally:
        winreg.CloseKey(key)


def _to_physical(x: float, y: float) -> tuple[int, int]:
    """Qt 逻辑坐标转成 UI Automation 用的物理像素。本机缩放 100% 时两者相同。"""
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return int(round(x)), int(round(y))
    app = QGuiApplication.instance()
    screen = None
    if app is not None:
        screen = app.screenAt(QPoint(int(x), int(y))) or app.primaryScreen()
    if screen is None:
        return int(round(x)), int(round(y))
    dpr = float(screen.devicePixelRatio() or 1.0)
    origin = screen.geometry().topLeft()
    px = origin.x() * dpr + (x - origin.x()) * dpr
    py = origin.y() * dpr + (y - origin.y()) * dpr
    return int(round(px)), int(round(py))


def _load_com():
    """只在 Windows 上加载一次。POINT 和函数指针必须是同一份类型。"""
    import ctypes
    from ctypes import POINTER, WINFUNCTYPE, c_int, c_long, c_void_p, wintypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class VARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("r1", ctypes.c_ushort),
            ("r2", ctypes.c_ushort),
            ("r3", ctypes.c_ushort),
            ("val", ctypes.c_ulonglong),
            ("pad", ctypes.c_ulonglong),
        ]

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = c_long
    ole32.CoCreateInstance.argtypes = [
        c_void_p, c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p),
    ]
    ole32.CoCreateInstance.restype = c_long
    oleaut = ctypes.WinDLL("oleaut32")
    oleaut.SysFreeString.argtypes = [c_void_p]
    return ctypes, POINTER, WINFUNCTYPE, c_int, c_long, c_void_p, POINT, VARIANT, ole32, oleaut


def _element_name_at(x: int, y: int) -> str | None:
    """屏幕物理坐标上的控件名称。失败返回 None，调用方就当不是「^」。"""
    global _UIA, _UIA_FAILED
    global _COM
    if sys.platform != "win32" or _UIA_FAILED:
        return None
    try:
        if _COM is None:
            _COM = _load_com()
        com = _COM
    except Exception:
        _UIA_FAILED = True
        return None
    if _UIA is None:
        _UIA = _create_uia(com)
        if _UIA is None:
            _UIA_FAILED = True
            return None
    ctypes, POINT, from_point, read_name, release, obj = _UIA
    element = com[5]()  # c_void_p
    hr = from_point(obj, POINT(int(x), int(y)), ctypes.byref(element))
    if hr != 0 or not element.value:
        return None
    try:
        return read_name(element)
    finally:
        release(element)


def _create_uia(com):
    ctypes, POINTER, WINFUNCTYPE, c_int, c_long, c_void_p, POINT, VARIANT, ole32, oleaut = com
    # COINIT_APARTMENTTHREADED。界面线程通常已经初始化过，S_FALSE(1) 也算成功。
    status = int(ole32.CoInitializeEx(None, 2)) & 0xFFFFFFFF
    if status not in (0, 1):
        return None

    def guid(text: str):
        return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

    obj = c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(guid(_CLSID)), None, 1,
        ctypes.byref(guid(_IID)), ctypes.byref(obj),
    )
    if hr != 0 or not obj.value:
        return None
    vt = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    from_point = WINFUNCTYPE(c_long, c_void_p, POINT, POINTER(c_void_p))(vt[7])

    def read_name(element):
        evt = ctypes.cast(element, POINTER(POINTER(c_void_p)))[0]
        get_prop = WINFUNCTYPE(c_long, c_void_p, c_int, POINTER(VARIANT))(evt[10])
        var = VARIANT()
        code = get_prop(element, _NAME_PROP, ctypes.byref(var))
        if code != 0 or var.vt != 8 or not var.val:
            return None
        try:
            return ctypes.wstring_at(var.val)
        finally:
            oleaut.SysFreeString(c_void_p(var.val))

    def release(element):
        evt = ctypes.cast(element, POINTER(POINTER(c_void_p)))[0]
        WINFUNCTYPE(c_long, c_void_p)(evt[2])(element)

    return ctypes, POINT, from_point, read_name, release, obj
