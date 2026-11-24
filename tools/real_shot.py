# -*- coding: utf-8 -*-
"""真机取景：抓当前桌面，把浅色卡片按位置摆上去，出 1:1 图看材质。

用法：python tools/real_shot.py [veil] [grain]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "app"))

from PySide6.QtCore import QPoint, QRect, Qt                     # noqa: E402
from PySide6.QtGui import QGuiApplication, QPainter               # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

import theme                                                      # noqa: E402
from model import Device, KEYBOARD, MOUSE                         # noqa: E402
from ui import glasscard                                          # noqa: E402
from ui.card import CardWindow                                    # noqa: E402


class FakeConfig:
    def __init__(self):
        self.data = {"interval_minutes": 10, "autostart": False, "theme": "dark",
                     "glass": True, "overrides": {}}

    def get(self, k, d=None):
        return self.data.get(k, d)

    def set(self, k, v):
        self.data[k] = v

    @property
    def interval_minutes(self):
        return int(self.data["interval_minutes"])


def main() -> int:
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    veil = float(args["veil"]) if "veil" in args else None
    grain = float(args["grain"]) if "grain" in args else None
    blur = float(args["blur"]) if "blur" in args else None
    mode = args.get("mode", "light")
    if blur is not None:
        import ui.card as cardmod
        cardmod.LIGHT_BLUR = blur
    if veil is not None:
        glasscard.LIGHT_VEIL = veil
    if grain is not None:
        glasscard.LIGHT_GRAIN = grain

    app = QApplication(sys.argv)
    theme.set_mode(mode)
    app.setStyleSheet(theme.qss())

    from PySide6.QtGui import QImage

    screen = QGuiApplication.primaryScreen()
    geo = screen.availableGeometry()
    desk_path = BASE / "docs" / "_desk.png"
    if "fresh" in sys.argv or not desk_path.exists():
        desk = screen.grabWindow(0).toImage()
        desk.save(str(desk_path))       # 同一张桌面，多次参数对比才公平
        print("已抓取新桌面")
    else:
        desk = QImage(str(desk_path))
    dpr = desk.width() / float(geo.width())

    devices = [
        Device(key="k1", name="VGN VXE75 V2", kind=KEYBOARD, level=82,
               source="Evision", transport="2.4G"),
        Device(key="m1", name="VXE R1 SE", kind=MOUSE, level=46,
               source="Evision", transport="2.4G"),
    ]

    card = CardWindow(FakeConfig())
    card.setAttribute(Qt.WA_DontShowOnScreen, True)
    card.set_devices(devices, animate=False)
    card.resize(card.sizeHint())

    # 摆在屏幕右下、任务栏上方，跟实际弹出来的位置一致
    w, h = card.width(), card.height()
    x = geo.right() - w - 24
    y = geo.bottom() - h - 12
    card.move(QPoint(x, y))
    ok = card._grab_backdrop()          # 真实抓屏 + 真实模糊参数
    card.card.attach(card._blur)
    card.card.set_enabled(True)
    card.show()
    QApplication.processEvents()
    pm = card.grab()

    scene = desk.copy()
    p = QPainter(scene)
    p.drawPixmap(QRect(int(x * dpr), int(y * dpr),
                       int(pm.width()), int(pm.height())), pm)
    p.end()

    pad = 30
    crop = scene.copy(QRect(int(x * dpr) - pad, int(y * dpr) - pad,
                            int(pm.width()) + pad * 2, int(pm.height()) + pad * 2))
    tag = f"{mode}_v{veil}_g{grain}_b{blur}"
    out = BASE / "docs" / f"shot_{tag}.png"
    crop.save(str(out))
    print(f"底图={'OK' if ok else '失败'} 产出={out}  {crop.width()}x{crop.height()}")
    card.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
