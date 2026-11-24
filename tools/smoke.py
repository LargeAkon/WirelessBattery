# -*- coding: utf-8 -*-
"""离屏冒烟测试：不弹窗，只验证界面构建与数据流。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from PySide6.QtWidgets import QApplication  # noqa: E402

from config import Config  # noqa: E402
from model import Device, HEADSET, KEYBOARD, MOUSE  # noqa: E402
from scanner import Scanner  # noqa: E402
from ui.card import CardWindow  # noqa: E402
from ui.diag import DiagWindow  # noqa: E402

devices = [
    Device(key="a", name="VXE75 V2", kind=KEYBOARD, level=76, source="自定义报文规则", transport="2.4G 接收器"),
    Device(key="b", name="Game Mouse", kind=MOUSE, level=23, source="自定义报文规则", transport="2.4G 接收器"),
    Device(key="c", name="WH-1000XM5", kind=HEADSET, level=55, charging=True, source="系统设备电量", transport="蓝牙"),
]

app = QApplication([])
config = Config()
card = CardWindow(config)
card.set_devices(devices)
card.adjustSize()
print("card size:", card.size())
card.toggle_settings()
card.adjustSize()
print("card size (settings):", card.size())
card.hide()

diag = DiagWindow(config)
diag.update_devices(devices, [])
print("diag pages:", diag.stack.count(), "rows:", diag.list_lay.count())

t0 = time.time()
scanner = Scanner(config)
found, debug = scanner.scan(with_debug=True)
print(f"scan took {time.time() - t0:.2f}s, devices={len(found)}")
for line in debug:
    print("  ", line)
for d in found:
    print("   ->", d.name, d.type_label, d.level, d.charging, d.source)
print("SMOKE OK")
