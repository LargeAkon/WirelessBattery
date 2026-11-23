# -*- coding: utf-8 -*-
"""一次扫描只向系统要一份 HID 清单，各通道共用。

原先每个通道各自 hid.enumerate()，点一次刷新就会同时躺着六七份
完整设备表。这里收成一份，并且只留下读电量真正用到的字段。
"""
from __future__ import annotations

from contextlib import contextmanager

_KEEP = (
    "path", "vendor_id", "product_id", "usage_page", "usage",
    "interface_number", "product_string", "manufacturer_string",
)
_current: list[dict] | None = None


def _load() -> list[dict]:
    try:
        import hid
    except Exception:
        return []
    try:
        raw = hid.enumerate()
    except Exception:
        return []
    slim = [{key: info.get(key) for key in _KEEP} for info in raw]
    del raw
    return slim


def devices() -> list[dict]:
    """扫描进行中返回共享清单；单独调用时现查一份。"""
    if _current is not None:
        return _current
    return _load()


@contextmanager
def shared():
    global _current
    if _current is not None:
        yield _current
        return
    listed = _load()
    _current = listed
    try:
        yield listed
    finally:
        _current = None
