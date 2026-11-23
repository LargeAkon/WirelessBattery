# -*- coding: utf-8 -*-
"""把卡片渲染成 PNG，便于校验视觉（不需要弹窗）。"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from PySide6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from config import Config  # noqa: E402
from model import Device, HEADSET, KEYBOARD, MOUSE  # noqa: E402
from ui.card import CardWindow  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "preview"
OUT.mkdir(exist_ok=True)

devices = [
    Device(key="k", name="VGN VXE75 V2", kind=KEYBOARD, level=44,
           source="Evision 2.4G", transport="2.4G 接收器"),
    Device(key="m", name="Game Mouse", kind=MOUSE, level=18,
           source="Evision 2.4G", transport="2.4G 接收器"),
    Device(key="h", name="WH-1000XM5", kind=HEADSET, level=55, charging=True,
           source="系统设备电量", transport="蓝牙"),
]

app = QApplication(sys.argv)
cfg = Config()

for mode in ("dark", "light"):
    theme.set_mode(mode)
    app.setStyleSheet(theme.qss())
    card = CardWindow(cfg)
    card.set_devices(devices, animate=False)
    card._relayout()
    card.adjustSize()
    app.processEvents()
    pm = card.grab()
    pm.save(str(OUT / f"card_{mode}.png"))
    print("saved", f"card_{mode}.png", pm.size())

    card.toggle_settings()
    app.processEvents()
    pm2 = card.grab()
    pm2.save(str(OUT / f"card_{mode}_settings.png"))
    print("saved", f"card_{mode}_settings.png", pm2.size())

# 空状态
theme.set_mode("dark")
card2 = CardWindow(cfg)
card2.set_devices([])
card2._relayout()
app.processEvents()
card2.grab().save(str(OUT / "card_empty.png"))
print("saved empty")
