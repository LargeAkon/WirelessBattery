# -*- coding: utf-8 -*-
"""HidD_SetOutputReport：用控制管道发 OUTPUT 报文。

有些接收器（HyperX Cloud III Wireless 这类 HP 系）没有可用的中断 OUT 端点，
命令必须走 SET_REPORT 控制传输；hidapi 的 write() 走中断管道，写进去等于没写，
设备不会有任何应答。Linux 那边的 hid-hyperx-headset 驱动同样用
hid_hw_raw_request(HID_OUTPUT_REPORT) 发命令，原因就在这里。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_INVALID_HANDLE = ctypes.c_void_p(-1).value


def set_output_report(path, packet: bytes) -> bool:
    """把 packet 当作 OUTPUT 报文发出去（首字节是报告号）。成功返回 True。"""
    if not packet:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hid_dll = ctypes.WinDLL("hid")
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    hid_dll.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_char_p,
                                             wintypes.ULONG]
    hid_dll.HidD_SetOutputReport.restype = wintypes.BOOLEAN

    text = path.decode("utf-8", "ignore") if isinstance(path, bytes) else str(path)
    handle = kernel32.CreateFileW(
        text, _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None, _OPEN_EXISTING, 0, None)
    if not handle or handle == _INVALID_HANDLE:
        return False
    try:
        buf = ctypes.create_string_buffer(bytes(packet), len(packet))
        return bool(hid_dll.HidD_SetOutputReport(handle, buf, len(packet)))
    finally:
        kernel32.CloseHandle(handle)
