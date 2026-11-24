# -*- coding: utf-8 -*-
"""换肤动效：新皮肤从点击处以圆形扩散铺满，旧皮肤被一点点收掉。

做法是"两张图 + 一个圆"：换肤前后的窗口各截一张，把旧图整张贴上，
再用圆形裁剪把新图叠上去，半径从 0 长到盖住整张窗口。

两个结构性决定，都是被实际毛病逼出来的：
1. 浮层是一张**独立的顶层窗口**，不是卡片的子控件 —— 子控件每重绘一帧，
   整张卡片都要跟着重新合成一遍，长动画必掉帧；独立窗口的逐帧重绘完全
   不碰卡片，只剩两张位图的搬运。
2. 盖板尺寸严格等于卡片窗口（两者现在本来就一样大：卡片四周那圈投影已经
   去掉，0 留白）。半透明像素叠加只会越来越黑，所以任何"比卡片多盖一圈"
   的做法都会在圆内留下更黑的一圈，收尾时又突然变淡，看着像抖一下。

要模仿的那套效果的关键还有两点，缺一个就变成普通淡入：
- 圆的圆心是**鼠标点的那个按钮**，不是窗口中心；
- 揭开的边缘有一圈极淡的亮环，暗色变亮色时像一层玻璃被掀开。

防闪的时序（由 CardWindow 编排）：先盖浮层（此刻还是旧皮肤，怎么画
都不会闪）→ 换肤 → 新皮肤在盖板下面画完 → 截新图 → 圆形揭开。
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, Qt,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

DURATION_MS = 780
# 圆的起手半径：得先把"点下去的那个控件"整个翻过去，不能从 0 长。
# 从 0 开始的话，头一两帧圆还没盖到开关，观感是"点了按钮没动"，
# 要等圆扩过来才看到切换。26px 刚好罩住 40x22 的开关。
START_RADIUS = 26.0


class RevealOverlay(QWidget):
    """盖在卡片窗口上播一次圆形揭开，播完自己关掉。

    独立顶层窗口 + WindowTransparentForInput：不抢焦点、点击穿透，
    换肤时用户可能还在点下一个选项；也不会被截进宿主窗口的 grab 里。

    WindowDoesNotAcceptFocus 是后加的一道保险：光靠
    WA_ShowWithoutActivating，Windows 偶尔还是会在这场"盖板出现/销毁"
    里给宿主补一个假失活 —— 表现是点一下外观颜色，卡片当场消失。
    声明"这个窗口不接受焦点"能挡住这类激活抖动（宿主侧另有一道核对）。
    """

    def __init__(self, host: QWidget, old: QPixmap, center: QPoint,
                 target: QRect | None = None,
                 duration: int = DURATION_MS, on_closed=None):
        super().__init__(None)
        self._host = host
        self._old = old
        self._new: QPixmap | None = None
        self._center = QPointF(center)
        self._progress = 0.0
        self._duration = max(120, int(duration))
        self._full = 1.0
        # 盖板原来要躲开窗口给投影留的那圈边，现在卡片没有投影、窗口就是
        # 卡片本体，所以盖板直接贴整个窗口（target 由宿主按卡片矩形传入）。
        self._target = QRect(target) if target is not None else QRect(host.geometry())
        # 播完自动 deleteLater，宿主必须第一时间把引用清掉，
        # 否则下次碰到就是个悬空的 C++ 包装，一调用就崩
        self._on_closed = on_closed

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.setGeometry(self._target)
        if old.isNull() or self.width() <= 0 or self.height() <= 0:
            self._host = None          # 无效：调用方按 close 处理
            self.close_reveal()
            return

        self._full = self._max_radius()
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self._duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        # 缓动用 OutQuad：起手就有速度，收尾匀速收到停。
        # 千万别用 InOutCubic —— 那条曲线在 t=0 的斜率是 0，头 150ms 圆几乎
        # 长不动（实测 82ms 时半径只从 26 变到 26.3），点完按钮像是卡了一下
        # 才开始动。OutQuad 第一帧就往外扩（100ms 已扩出 70 多像素），
        # 又不像 OutCubic 那样前端过猛，整体节奏更平。
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.finished.connect(self.close_reveal)
        self.show()
        self.raise_()

    # ---------------- 生命周期 ----------------
    @property
    def active(self) -> bool:
        return self._host is not None

    def sync_geometry(self, target: QRect | None = None) -> None:
        """宿主挪窝/变尺寸时跟着走，别让盖板悬在旧位置。"""
        if self._host is None:
            return
        self._target = QRect(target) if target is not None else QRect(self._host.geometry())
        self.setGeometry(self._target)
        self._full = self._max_radius()

    def set_new_and_start(self, new: QPixmap) -> None:
        """换肤完成，喂新图并开始圆形揭开。尺寸对不上就放弃动效。"""
        if self._host is None:
            return
        if new.isNull() or new.size() != self._old.size():
            self.close_reveal()
            return
        self._new = new
        self._anim.start()

    def close_reveal(self) -> None:
        self._anim.stop()
        self._host = None
        cb = self._on_closed
        self._on_closed = None
        self.hide()
        self.deleteLater()
        if cb is not None:
            cb(self)

    # ---------------- 动画属性 ----------------
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, get_progress, set_progress)

    def _max_radius(self) -> float:
        w, h = float(self.width()), float(self.height())
        dx = max(self._center.x(), w - self._center.x())
        dy = max(self._center.y(), h - self._center.y())
        return math.hypot(dx, dy) + 2.0

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        if self._host is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if not self._old.isNull():
            p.drawPixmap(0, 0, self._old)

        radius = max(START_RADIUS, self._full * self._progress)
        if self._new is None or radius <= 0.5:
            p.end()
            return

        clip = QPainterPath()
        clip.addEllipse(self._center, radius, radius)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(0, 0, self._new)
        p.restore()

        # 边沿亮环：只走前 78% 的行程，末尾淡出，避免最后一帧出现一圈硬边
        if self._progress < 0.78:
            fade = 1.0 - self._progress / 0.78
            ring = QPen(QColor(255, 255, 255, int(72 * fade)))
            ring.setWidthF(1.4)
            p.setPen(ring)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._center, radius, radius)
        p.end()


__all__ = ["RevealOverlay", "DURATION_MS"]
