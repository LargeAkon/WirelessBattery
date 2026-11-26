# -*- coding: utf-8 -*-
"""鼠标停在托盘图标上就弹出电量卡片。

Windows 的托盘浮层是 Explorer 自己画的，Qt 收不到 hover 事件，只能轮询：
每 120ms 取一次光标位置，和托盘图标的屏幕矩形比对。矩形来自
QSystemTrayIcon.geometry()（Qt 6 在 Windows 上走 Shell_NotifyIconGetRect），
坐标是逻辑像素，和 QCursor.pos() 同一套，不用自己乘 DPI。

三个必须处理的边角情况：
1. 图标被折叠进「^」里时拿不到矩形 —— 整段逻辑静默关闭，仍然显示原生
   文字提示，点一下也照样能开卡片；
2. 用户点图标把卡片收起来之后，光标还压在图标上，不该立刻又被悬停打开，
   所以光标离开图标之前一直保持静默（mute）；
3. 鼠标从图标移向卡片时要经过一段"谁都不属于"的边界 —— 收起动作延迟
   260ms 再做，且卡片自己也参与命中判断，不会一路走一路闪。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ui.card import tray_rect_ok

POLL_MS = 120          # 8 次/秒：够快，又不至于让 CPU 常驻
LEAVE_MS = 260         # 离开后延迟收起，跨过图标与卡片之间的缝隙
REOPEN_MS = 450        # 刚收起这么短时间内不再自动弹出（连着点图标时防抖）


class TrayHover(QObject):
    """托盘图标悬停 → 卡片。只做这一件事，动作都交给 card。"""

    supported_changed = Signal(bool)

    def __init__(self, tray: QSystemTrayIcon, card, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.card = card
        self._rect = QRect()
        self._supported = False
        self._muted = False
        self._last_hide = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        # 位置每 600ms 才重新问一次 Shell：光标坐标是本地读的，很便宜；
        # Shell_NotifyIconGetRect 要走一次跨进程调用，没必要 8 次/秒都问。
        self._ticks = 0

        self._leave = QTimer(self)
        self._leave.setSingleShot(True)
        self._leave.setInterval(LEAVE_MS)
        self._leave.timeout.connect(self._maybe_hide)

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._leave.stop()

    @property
    def supported(self) -> bool:
        return self._supported

    def mute(self) -> None:
        """用户主动收起卡片：光标还在图标上就别再弹出来。"""
        self._muted = True
        self._last_hide = time.monotonic()
        self._leave.stop()

    # ---------------- 轮询 ----------------
    def _refresh_rect(self) -> None:
        rect = self.tray.geometry()
        # 只认"一枚图标"大小的矩形。有的系统在全屏应用前台 / 切分辨率之后
        # 会把整条任务栏或通知区域丢回来，宽高几百像素；拿它当悬停热区，
        # 鼠标扫过任务栏就会弹卡片，落位也会跑到屏幕中间。
        ok = tray_rect_ok(rect)
        self._rect = QRect(rect) if ok else QRect()
        if ok != self._supported:
            self._supported = ok
            self.supported_changed.emit(ok)

    def _poll(self) -> None:
        self._ticks += 1
        if self._ticks % 5 == 1 or self._rect.isNull():
            self._refresh_rect()
        if not self._supported or not self.tray.isVisible():
            return

        pos = QCursor.pos()
        over_icon = self._rect.adjusted(-1, -1, 1, 1).contains(pos)
        if not over_icon:
            self._muted = False

        if over_icon:
            self._leave.stop()
            if self._openable():
                self.card.show_near(self._rect, activate=False)
            return

        if not self.card.isVisible():
            return
        if self._over_card(pos):
            self._leave.stop()
            return
        # 只自动收起"悬停弹出的"那种；点开的卡片仍按原来的失焦逻辑走，
        # 否则从菜单打开设置时，鼠标一离开就被关掉了
        if self.card._hover_shown and not self._leave.isActive():
            self._leave.start()

    def _openable(self) -> bool:
        if self._muted or self.card.isVisible():
            return False
        # 右键菜单（或任何弹出层）正开着时别再冒一张卡片出来
        if QApplication.activeModalWidget() is not None:
            return False
        if QApplication.activePopupWidget() is not None:
            return False
        if self.card.hidden_recently(REOPEN_MS / 1000.0):
            return False
        return (time.monotonic() - self._last_hide) > (REOPEN_MS / 1000.0)

    def _over_card(self, pos) -> bool:
        if not self.card.isVisible():
            return False
        geo = self.card.frameGeometry()
        return geo.adjusted(-8, -8, 8, 8).contains(pos)

    def _maybe_hide(self) -> None:
        if not self.card.isVisible():
            return
        # 换肤/毛玻璃的圆形揭开还没播完：这会儿收起来，动效等于被剪掉。
        # 等下一轮再判断。
        if self.card.reveal_active():
            self._leave.start()
            return
        pos = QCursor.pos()
        if self._over_card(pos) or self._rect.contains(pos):
            return
        if QApplication.activeModalWidget() is not None:
            return
        self._last_hide = time.monotonic()
        self.card.hide_card()


__all__ = ["TrayHover"]
