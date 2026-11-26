# -*- coding: utf-8 -*-
"""换肤动效：新皮肤从点击处以圆形扩散铺满，旧皮肤被一点点收掉。

做法是"两张图 + 一个圆"：换肤前后的卡片各截一张，把旧图整张贴上，
再用圆形裁剪把新图叠上去，半径从 0 长到盖住整张卡片。

**它是一个子控件，不是独立窗口。**

早先这里是"独立顶层窗口 + 逐帧重绘不碰卡片"的思路，被实际问题一个个
推翻：那块浮层会被系统当成另一个窗口，于是
1. 它一出现/消失，Windows 就给卡片补一个假失活，卡片当场消失；
2. 全屏游戏在前台时，置顶不一定压得住，动效直接看不见；
3. 一旦落位算错或没收掉，它就孤零零挂在屏幕上 —— 用户看到的就是
   "屏幕中间那张若隐若现的卡片照片"，而且鼠标点不动；
4. 它和卡片是两张皮：卡片重绘（换肤必然全窗重刷）和它不同帧，
   中间那一帧就是"闪一下"。

做成子控件后这四条一起消失：它只能待在卡片里，跟着卡片一起被合成，
不会改变前台窗口，也不存在"留下孤儿浮层"这种状态 —— 卡片藏了它跟着藏。
每帧代价是一张 344×273 的窗口重绘，实测一帧不到 1ms，换肤动效完全够用。

要模仿的那套效果的关键还有两点，缺一个就变成普通淡入：
- 圆的圆心是**鼠标点的那个按钮**，不是窗口中心；
- 揭开的边缘有一圈极淡的亮环，暗色变亮色时像一层玻璃被掀开。

防闪的时序（由 CardWindow 编排）：先盖浮层（此刻还是旧皮肤，怎么画
都不会闪）→ 换肤 → 新皮肤在盖板下面画完 → 截新图 → 圆形揭开。
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, Qt,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

DURATION_MS = 780
# 圆的起手半径：得先把"点下去的那个控件"整个翻过去，不能从 0 长。
# 从 0 开始的话，头一两帧圆还没盖到开关，观感是"点了按钮没动"，
# 要等圆扩过来才看到切换。26px 刚好罩住 40x22 的开关。
START_RADIUS = 26.0


class RevealOverlay(QWidget):
    """盖在卡片上的圆形揭开，播完自己关掉。

    是**宿主的子控件**：铺满宿主、不吃鼠标（WA_TransparentForMouseEvents），
    所以换肤时用户还能接着点下一个选项，也不会被截进宿主自己的截图里
    （宿主截图前会先把它藏起来一瞬，见 CardWindow._card_snapshot）。
    """

    def __init__(self, host: QWidget, old: QPixmap, center: QPoint,
                 duration: int = DURATION_MS, on_closed=None):
        super().__init__(host)
        self._host = host
        self._old = old
        self._new: QPixmap | None = None
        self._center = QPointF(center)
        self._progress = 0.0
        self._duration = max(120, int(duration))
        self._full = 1.0
        # 先占位：下面尺寸无效时会走 close_reveal()，它要停动画。
        self._anim: QPropertyAnimation | None = None
        self._closed = False
        # 尺寸不一致时（换肤改了字体度量、卡片高度跟着变）旧图按右下角
        # 对齐 —— 卡片底边钉在托盘上方、右边贴屏幕边，右下角是不动的那个角。
        self._old_at = QPoint(0, 0)
        # 播完自动 deleteLater，宿主必须第一时间把引用清掉，
        # 否则下次碰到就是个悬空的 C++ 包装，一调用就崩
        self._on_closed = on_closed

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 不铺底色：透明的地方露出来的应该是卡片本身，不是一块灰色
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

        self.setGeometry(host.rect())
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
        return self._host is not None and not self._closed

    def animating(self) -> bool:
        anim = self._anim
        return bool(anim is not None and anim.state() == QPropertyAnimation.Running)

    def sync_geometry(self) -> None:
        """宿主尺寸变了就跟着铺满。子控件不会自己跟着长，得手动对齐。"""
        host = self._host
        if host is None:
            return
        self.setGeometry(host.rect())
        self._full = self._max_radius()

    def set_new_and_start(self, new: QPixmap) -> None:
        """换肤完成，喂新图并开始圆形揭开。

        以前这里尺寸对不上就直接放弃动效，结果是"点了颜色，画面啪一下
        变过去"——因为换肤偶尔真的会改高度（字体度量回退、行高差一像素）。
        现在按右下角对齐，照播不误。
        """
        if not self.active or self._anim is None:
            return
        if new.isNull():
            self.close_reveal()
            return
        host = self._host
        if host is not None and (self.width() != host.width()
                                 or self.height() != host.height()):
            self.sync_geometry()
        self._new = new
        dpr = self._old.devicePixelRatio() or 1.0
        old_w = self._old.width() / dpr
        old_h = self._old.height() / dpr
        dx = round(self.width() - old_w)
        dy = round(self.height() - old_h)
        if dx or dy:
            self._old_at = QPoint(dx, dy)
            # 控件在卡片里的坐标也跟着挪了同样的距离，圆心必须一起走，
            # 否则圆会从按钮旁边长出来
            self._center = QPointF(self._center.x() + dx, self._center.y() + dy)
        self._anim.start()

    def close_reveal(self) -> None:
        """关掉盖板。可重复调用：看门狗、动画结束、宿主收起都可能来一次。"""
        if self._closed:
            return
        self._closed = True
        anim = self._anim
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
        self._host = None
        try:
            self.hide()
        except Exception:
            pass
        cb = self._on_closed
        self._on_closed = None
        try:
            self.deleteLater()
        except Exception:
            pass
        if cb is not None:
            cb(self)

    # ---------------- 动画属性 ----------------
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = float(value)
        # 子控件必须是整块重绘：圆的边界每帧都在变，局部刷新会留下残影
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
            p.drawPixmap(self._old_at, self._old)

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
