# -*- coding: utf-8 -*-
"""坐标诊断：打印托盘图标与卡片窗口的几何信息。"""
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

    def report() -> None:
        tray_app.show_card()
        card = tray_app.card
        screen = app.primaryScreen()
        print("screen geo     :", screen.geometry())
        print("screen avail   :", screen.availableGeometry())
        print("devicePixelRatio:", screen.devicePixelRatio())
        print("tray geometry  :", tray_app.tray.geometry())
        print("tray available :", tray_app.tray.isSystemTrayAvailable())
        print("card geometry  :", card.geometry())
        print("card visible   :", card.isVisible())
        QTimer.singleShot(2500, lambda: print("after 2.5s card:", card.geometry()))

    QTimer.singleShot(4000, report)
    QTimer.singleShot(12000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
