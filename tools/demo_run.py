# -*- coding: utf-8 -*-
"""演示模式：启动后自动弹出卡片，便于截图核对真实渲染效果。"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main as entry  # noqa: E402


def run() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray_app = entry.TrayApp(app)
    QTimer.singleShot(4000, tray_app.show_card)
    QTimer.singleShot(60000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
