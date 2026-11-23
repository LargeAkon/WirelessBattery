# -*- coding: utf-8 -*-
"""托盘图标预览：单台 / 两台 / 三台的最终观感（含任务栏拟真条）。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "app"))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ui import icons
from model import KEYBOARD, MOUSE, HEADSET

CASES = [
    ("一台 · 键盘 45%", [(KEYBOARD, 45)]),
    ("两台 · 键盘45 鼠标72", [(KEYBOARD, 45), (MOUSE, 72)]),
    ("三台 · 键45 鼠72 耳90", [(KEYBOARD, 45), (MOUSE, 72), (HEADSET, 90)]),
    ("三台 · 都很低 12/18/25", [(KEYBOARD, 12), (MOUSE, 18), (HEADSET, 25)]),
    ("三台 · 其一暂时无数据", [(KEYBOARD, 45), (MOUSE, None), (HEADSET, 90)]),
    ("未识别到设备", []),
]

DARK = "#1C1C1F"
LIGHT = "#EFEFF2"
ZOOM = 6


def main() -> None:
    app = QApplication(sys.argv)
    label_w, cell_w, cell_h = 190, 150, 104
    w = label_w + cell_w * 3
    h = 34 + cell_h * len(CASES) + 48
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setFont(QFont("Microsoft YaHei UI", 8))

    p.setPen(QColor("#888"))
    for i, text in enumerate(["实际大小（深色任务栏）", "实际大小（浅色任务栏）", "放大 6 倍"]):
        p.drawText(QRectF(label_w + i * cell_w, 6, cell_w, 22), Qt.AlignCenter, text)

    for r, (name, entries) in enumerate(CASES):
        y = 34 + r * cell_h
        p.fillRect(QRectF(0, y, label_w - 8, cell_h - 8), QColor("#F6F6F8"))
        p.setPen(QColor("#111"))
        p.drawText(QRectF(10, y, label_w - 20, cell_h - 8),
                   Qt.AlignLeft | Qt.AlignVCenter, name)
        for c, (size, bg) in enumerate([(16, DARK), (16, LIGHT), (16, DARK)]):
            box = QRectF(label_w + c * cell_w, y, cell_w - 8, cell_h - 8)
            p.fillRect(box, QColor(bg))
            ink = "#FFFFFF" if bg == DARK else "#0A0B0C"
            pm = icons.tray_pixmap_for(entries, ink, size)
            cy = box.center().y()
            if c < 2:
                p.drawPixmap(QRectF(box.left() + 24, cy - size / 2, size, size), pm,
                             QRectF(0, 0, size, size))
            else:
                zw = size * ZOOM
                big = pm.scaled(zw, zw, Qt.KeepAspectRatio, Qt.FastTransformation)
                p.drawPixmap(QRectF(box.center().x() - zw / 2, cy - zw / 2, zw, zw),
                             big, QRectF(0, 0, big.width(), big.height()))

    # 拟真任务栏条：托盘图标混在其它托盘图标之间
    y = 34 + cell_h * len(CASES) + 6
    p.fillRect(QRectF(0, y, w, 38), QColor(DARK))
    p.setPen(QColor("#8E939A"))
    p.drawText(QRectF(14, y, 150, 38), Qt.AlignLeft | Qt.AlignVCenter, "任务栏示意图")
    x = w - 300
    for idx, (_, entries) in enumerate(CASES[:3]):
        ix = x + idx * 64
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#55585E"))
        p.drawEllipse(QRectF(ix - 30, y + 11, 16, 16))
        pm = icons.tray_pixmap_for(entries, "#FFFFFF", 16)
        p.drawPixmap(QRectF(ix, y + 11, 16, 16), pm, QRectF(0, 0, 16, 16))
    p.end()
    out = BASE / "preview" / "tray_multi.png"
    img.save(str(out))
    print(out, img.width(), img.height())


if __name__ == "__main__":
    main()
