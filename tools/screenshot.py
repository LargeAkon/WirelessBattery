# -*- coding: utf-8 -*-
"""用 Qt 抓取整个屏幕，便于核对真实渲染。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("screen.png")
app = QGuiApplication(sys.argv)
screen = app.primaryScreen()
pm = screen.grabWindow(0)
pm.save(str(out))
print("saved", out, pm.size())
