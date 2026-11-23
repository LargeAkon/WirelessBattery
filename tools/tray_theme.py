# -*- coding: utf-8 -*-
"""托盘图标跟随主题的四种组合预览（含浅色任务栏下的可读性风险）。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "app"))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

import theme
from ui import icons
from model import KEYBOARD, MOUSE, HEADSET

DARK_BAR = "#1C1C1F"
LIGHT_BAR = "#F3F3F5"
CELL_W, CELL_H = 250, 118


def main() -> None:
    app = QApplication(sys.argv)
    w = CELL_W * 2 + 24
    h = CELL_H * 2 + 44
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setFont(QFont("Microsoft YaHei UI", 8))

    cases = [
        ("dark", DARK_BAR, "深色主题 · 深色任务栏"),
        ("dark", LIGHT_BAR, "深色主题 · 浅色任务栏"),
        ("light", LIGHT_BAR, "浅色主题 · 浅色任务栏"),
        ("light", DARK_BAR, "浅色主题 · 深色任务栏"),
    ]

    for i, (mode, bar, label) in enumerate(cases):
        theme.set_mode(mode)
        ink = theme.tray_icon_color(taskbar_light=(bar == LIGHT_BAR))
        col, row = i % 2, i // 2
        x = 12 + col * CELL_W
        y = 12 + row * CELL_H
        box = QRectF(x, y, CELL_W - 12, CELL_H - 12)
        p.fillRect(box, QColor(bar))
        p.setPen(QColor("#8A8F96"))
        p.drawText(QRectF(box.left(), box.top() + 4, box.width(), 16),
                   Qt.AlignCenter, label)

        entries = [(KEYBOARD, 44), (MOUSE, 72), (HEADSET, 90)]
        pm = icons.tray_pixmap_for(entries, ink, 16)
        one = icons.tray_pixmap_for([(KEYBOARD, 44)], ink, 16)
        cy = box.center().y() + 6
        p.drawPixmap(QRectF(box.left() + 40, cy - 8, 16, 16), one, QRectF(0, 0, 16, 16))
        p.drawPixmap(QRectF(box.left() + 88, cy - 8, 16, 16), pm, QRectF(0, 0, 16, 16))
        big = pm.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(QRectF(box.left() + 140, cy - 24, 48, 48), big,
                     QRectF(0, 0, 48, 48))
    p.end()
    out = BASE / "preview" / "tray_theme.png"
    img.save(str(out))
    print(out, img.width(), img.height())


if __name__ == "__main__":
    main()
