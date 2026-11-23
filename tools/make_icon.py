# -*- coding: utf-8 -*-
"""生成 app.ico 与安装向导用的勾选框贴图。"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import icons  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)

app = QApplication(sys.argv)

# Qt 的 ICO 写入只支持单张图，这里写 256x256，Windows 会自动缩放
pm = icons.app_icon(256)
target = OUT / "app.ico"
ok = pm.save(str(target), "ICO")
print("save ico:", ok, target, target.stat().st_size if target.exists() else 0)
pm.save(str(OUT / "app.png"), "PNG")


def _box(size: int = 96) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor("#C4C7CE"))
    pen.setWidthF(size * 0.075)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(size * 0.09, size * 0.09, size * 0.82, size * 0.82),
                      size * 0.22, size * 0.22)
    p.end()
    return pix


def _check(size: int = 96) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0A0B0C"))
    p.drawRoundedRect(QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88),
                      size * 0.24, size * 0.24)
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(size * 0.13)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([
        QPointF(size * 0.26, size * 0.52),
        QPointF(size * 0.44, size * 0.70),
        QPointF(size * 0.76, size * 0.32),
    ])
    p.end()
    return pix


_box().save(str(OUT / "box.png"), "PNG")
_check().save(str(OUT / "check.png"), "PNG")
print("checkbox assets saved")
