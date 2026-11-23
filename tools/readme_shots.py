# -*- coding: utf-8 -*-
"""生成 README 配图：卡片（浅/深）、诊断窗口、托盘图标一览。

用法（在项目根目录）：
    python tools/readme_shots.py

窗口用 WA_DontShowOnScreen 渲染：字形走真实平台，但窗口不会真的出现在屏幕上，
也不会抓到桌面内容（毛玻璃一律关掉，避免把用户桌面糊进图里）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from config import Config  # noqa: E402
from model import Device, HEADSET, KEYBOARD, MOUSE  # noqa: E402
from ui import icons  # noqa: E402
from ui.card import CardWindow  # noqa: E402
from ui.diag import DiagWindow  # noqa: E402

OUT = ROOT / "docs"

SAMPLE = [
    Device(key="a", name="PRO X 2", kind=MOUSE, level=47,
           source="HID++", transport="2.4G 接收器", charging=True),
    Device(key="b", name="VGN VXE75 V2", kind=KEYBOARD, level=100,
           source="Evision", transport="2.4G 接收器"),
    Device(key="c", name="Cloud III Wireless", kind=HEADSET, level=12,
           source="HyperX", transport="2.4G 接收器"),
]


def _prep(mode: str) -> None:
    theme.set_mode(mode)
    QApplication.instance().setStyleSheet(theme.qss())


def shot_card(mode: str, name: str) -> None:
    _prep(mode)
    cfg = Config()
    cfg.set("glass", False)          # 毛玻璃要抓屏，会把桌面内容带进图里
    win = CardWindow(cfg)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.set_devices(list(SAMPLE))
    win.show()
    QTest.qWait(1000)                # 等电量条填充动画走完
    win.grab().save(str(OUT / name))
    win.close()
    print("card   ->", name)


def shot_diag() -> None:
    _prep("light")
    win = DiagWindow(Config())
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.resize(880, 780)
    win.show()
    QTest.qWait(1200)
    win.update_devices(SAMPLE[:2], [])
    QTest.qWait(600)
    win.grab().save(str(OUT / "diag.png"))
    win.close()
    print("diag   -> diag.png")


def shot_tray() -> None:
    """按 6 倍分辨率渲染（相当于高分屏上的真实观感）。

    直接放大 16px 位图会得到一堆灰色噪点，看不出图标本身的设计；
    这里让绘制代码自己按 dpr=6 出图，边缘是干净的。
    """
    ink = theme.tray_icon_color()
    charge = theme.tray_charge_color()
    dpr = 6
    cell, gap, label_h = 16 * dpr, 30, 34

    def hi(pm: QPixmap) -> QPixmap:
        pm.setDevicePixelRatio(1.0)      # 交给下面按像素直接贴，不再缩一次
        return pm

    items = [
        ("100%", hi(icons.tray_pixmap(100, ink, 16, float(dpr)))),
        ("75%", hi(icons.tray_pixmap(75, ink, 16, float(dpr)))),
        ("45%", hi(icons.tray_pixmap(45, ink, 16, float(dpr)))),
        ("12%", hi(icons.tray_pixmap(12, ink, 16, float(dpr)))),
        ("未知", hi(icons.tray_pixmap(None, ink, 16, float(dpr)))),
        ("充电 30%", hi(icons._tray_charge_pixmap(ink, charge, 16, float(dpr), 0.30))),
        ("充电 70%", hi(icons._tray_charge_pixmap(ink, charge, 16, float(dpr), 0.70))),
        ("充满", hi(icons._tray_charge_pixmap(ink, charge, 16, float(dpr), 1.0))),
    ]

    pad = 26
    width = pad * 2 + len(items) * cell + (len(items) - 1) * gap
    height = pad * 2 + cell + label_h
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#F3F4F6"))       # 模拟浅色任务栏

    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    font = QFont("Microsoft YaHei UI", 9)
    p.setFont(font)
    for i, (label, pm) in enumerate(items):
        x = pad + i * (cell + gap)
        p.drawPixmap(x, pad, pm)
        p.setPen(QColor("#5B616E"))
        p.drawText(x - 12, pad + cell + 20, cell + 24, 18,
                   Qt.AlignHCenter | Qt.AlignVCenter, label)
    p.end()
    canvas.save(str(OUT / "tray.png"))
    print("tray   -> tray.png")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    QApplication([])
    shot_card("light", "card-light.png")
    shot_card("dark", "card.png")
    shot_diag()
    shot_tray()
    print("全部写入", OUT)


if __name__ == "__main__":
    main()
