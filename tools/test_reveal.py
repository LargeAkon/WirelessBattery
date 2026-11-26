# -*- coding: utf-8 -*-
"""换肤动效的离线回归：不许留盖板、不许把卡片甩到屏幕中间。

不用开真窗口（QT_QPA_PLATFORM=offscreen），跑法：
    python tools/test_reveal.py

这几条对应实际踩过的坑：
  1. 换肤中途某一行抛异常 —— 旧代码会让盖板永远留在屏幕上（一张卡片
     照片挂在桌面中央），动效也一起没了；
  2. Shell 把托盘矩形丢回屏幕中间 —— 卡片跟着落到屏幕中间；
  3. 动效播到一半又调了一次 show_near（悬停轮询 / 点托盘）—— 盖板不能
     变成孤儿；
  4. 盖板矩形必须与卡片完全重合，差一个像素就会在圆外多出一圈黑影。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="wb_reveal_")

APP = Path(os.environ.get("WB_APP")
           or (Path(__file__).resolve().parent.parent / "app"))
sys.path.insert(0, str(APP))

from PySide6.QtCore import QRect, QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication                      # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

import theme                                                   # noqa: E402
from config import Config                                      # noqa: E402
from model import Device                                       # noqa: E402
from ui.card import CardWindow                                 # noqa: E402
from ui.reveal import RevealOverlay                            # noqa: E402

FAILED: list[str] = []


def ok(name: str, passed: bool, detail: str = "") -> None:
    print(f"{'ok  ' if passed else 'FAIL'} {name}{('  ' + detail) if detail else ''}")
    if not passed:
        FAILED.append(name)


def qwait(ms: int) -> None:
    done = [False]
    QTimer.singleShot(ms, lambda: done.__setitem__(0, True))
    while not done[0]:
        QApplication.processEvents()


def stray() -> int:
    """还挂在屏幕上的盖板数量。"""
    return sum(1 for w in QApplication.allWidgets()
               if isinstance(w, RevealOverlay) and w.isVisible())


def overlays() -> list:
    return [w for w in QApplication.allWidgets()
            if isinstance(w, RevealOverlay) and w.isVisible()]


def main() -> int:
    app = QApplication(sys.argv)
    theme.set_mode("dark")
    app.setStyleSheet(theme.qss())
    cfg = Config()
    card = CardWindow(cfg)
    # 离屏环境没有真光标、也没有真前台窗口，失活核对会把卡片当"人已经走了"
    # 收起来（真机上光标正压在卡片里，走不到那一步）。关掉它，测的才是
    # 换肤链路本身。
    card._suppress_hide = True
    card.theme_changed.connect(
        lambda m: (theme.set_mode(m), app.setStyleSheet(theme.qss()), card.apply_theme()))
    scr = QGuiApplication.primaryScreen().availableGeometry()
    tray = QRect(scr.right() - 56, scr.bottom() - 30, 24, 24)

    card.set_devices([Device(key="k1", name="测试鼠标", kind="mouse", level=66,
                             source="测试")])
    card.show_near(tray)
    qwait(320)
    card.toggle_settings()
    qwait(260)

    # ④ 盖板：必须是卡片的子控件，且铺满卡片
    mode = "light" if theme.current_mode() == "dark" else "dark"
    card._theme_chips[mode].click()
    qwait(120)
    live = overlays()
    if live:
        rect = live[0].geometry()
        want = card.card.rect()
        ok("盖板铺满卡片", rect == want, f"{rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        ok("盖板是卡片的子控件（不再单独占一个窗口）",
           live[0].parent() is card.card and live[0].isWindow() is False,
           f"parent={type(live[0].parent()).__name__} isWindow={live[0].isWindow()}")
    else:
        ok("盖板铺满卡片", False, "没有盖板")
        ok("盖板是卡片的子控件（不再单独占一个窗口）", False, "没有盖板")
    qwait(1200)
    ok("动效播完不留盖板", stray() == 0, f"残留 {stray()}")

    # ⑤ 动效真的画出来了：中途那一帧必须是"旧图 + 圆内新图"的混合，
    #    既不是还没开始（和旧图一模一样），也不是一步到位（和新图一模一样）
    card.show_near(tray)
    qwait(320)
    if not card._settings_open:
        card.toggle_settings()
        qwait(260)

    def diff_ratio(a, b, step: int = 4) -> float:
        ia, ib = a.toImage(), b.toImage()
        n = 0
        bad = 0
        for y in range(0, ia.height(), step):
            for x in range(0, ia.width(), step):
                n += 1
                ca, cb = ia.pixelColor(x, y), ib.pixelColor(x, y)
                if (abs(ca.red() - cb.red()) > 6 or abs(ca.green() - cb.green()) > 6
                        or abs(ca.blue() - cb.blue()) > 6):
                    bad += 1
        return bad / max(1, n)

    before_pm = card.grab()
    mode = "light" if theme.current_mode() == "dark" else "dark"
    card._theme_chips[mode].click()
    qwait(200)
    during_pm = card.grab()
    ok("换肤动效跑起来了（截图这一刻盖板还在）", card._reveal is not None,
       f"prog={card._reveal._progress:.2f}" if card._reveal else "没有盖板")
    qwait(900)
    after_pm = card.grab()

    off_old = diff_ratio(during_pm, after_pm)     # 与"新图"不同的比例
    off_new = diff_ratio(during_pm, before_pm)    # 与"旧图"不同的比例
    ok("中途那一帧确实是旧图和新图叠在一起",
       0.05 < off_old < 0.95 and 0.05 < off_new < 0.95,
       f"与旧图差 {off_new:.0%} / 与新图差 {off_old:.0%}")

    # ③ 动效中途再调一次 show_near
    mode = "light" if theme.current_mode() == "dark" else "dark"
    card._theme_chips[mode].click()
    qwait(200)
    card.show_near(tray)
    qwait(1600)
    ok("中途重开不留盖板", stray() == 0, f"残留 {stray()}")

    # ① 换肤时某一行抛异常
    card.show_near(tray)
    qwait(320)
    rows = list(card._rows.values())
    if rows:
        def boom(*_a, **_kw):
            raise RuntimeError("模拟某一行渲染失败")

        rows[0].apply = boom
    before = theme.current_mode()
    mode = "light" if before == "dark" else "dark"
    card._theme_chips[mode].click()
    qwait(1600)
    ok("取换肤时某行抛异常不留盖板", stray() == 0, f"残留 {stray()}")
    ok("取换肤时异常也把颜色换掉", theme.current_mode() == mode,
       f"{before} -> {theme.current_mode()}")

    # ② 托盘矩形被丢回屏幕中间
    center = QRect(scr.center().x() - 12, scr.center().y() - 12, 24, 24)
    card.show_near(center)
    qwait(420)
    cx = card.x() + card.width() // 2
    ok("假托盘矩形不把卡片甩到屏幕中间", cx > scr.left() + scr.width() * 0.6,
       f"卡片中心 x={cx} 屏幕宽 {scr.width()}")
    ok("假托盘矩形时贴着屏幕右边", card.x() + card.width() >= scr.right() - 200,
       f"右边缘 {card.x() + card.width()} / {scr.right()}")

    print("全部通过" if not FAILED else f"失败 {len(FAILED)} 项: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
