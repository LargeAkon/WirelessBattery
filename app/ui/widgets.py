# -*- coding: utf-8 -*-
"""自定义控件：电量条、开关、图标按钮、设备行（单色极简，无框中框）。"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

import theme
from model import Device
from ui import icons


class BatteryBar(QWidget):
    """细电量条（4px），带数值过渡动画。

    充电时切换成"流动"形态：绿色渐变填充 + 一道高光沿轨道向前反复扫过，
    读起来就是能量正往里灌；不充电时仍是原来的单色墨条。
    """

    SWEEP_MS = 1700        # 高光扫一遍的时长
    FRAME_MS = 33          # ≈30fps：够顺滑，也不为一个 4px 条子白烧 CPU

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self._charging = False
        self._unavailable = False
        self._phase = 0.0
        self.setFixedHeight(4)
        self.setMinimumHeight(4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(520)
        self._anim.setEasingCurve(QEasingCurve.OutQuart)

        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(self.FRAME_MS)
        self._sweep_timer.timeout.connect(self._tick)

    def get_value(self) -> float:
        return self._value

    def set_value(self, v: float) -> None:
        self._value = float(v)
        self.update()

    value = Property(float, get_value, set_value)

    def set_level(self, level: float | None, animate: bool = True) -> None:
        target = 0.0 if level is None else max(0.0, min(100.0, level))
        self._anim.stop()
        if animate and abs(target - self._value) > 0.5:
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._value = target
            self.update()

    def set_charging(self, on: bool) -> None:
        on = bool(on)
        if on == self._charging:
            return
        self._charging = on
        if on:
            self._phase = 0.0
            self._sweep_timer.start()
        else:
            self._sweep_timer.stop()
        self.update()

    def set_unavailable(self, on: bool) -> None:
        """设备存在、但没有电量通道。用虚线表示"无数据"。

        直接留空条会被读成 0%（等于"快没电了"），这是完全相反的含义。
        """
        on = bool(on)
        if on == self._unavailable:
            return
        self._unavailable = on
        self.update()

    def _tick(self) -> None:
        # 卡片收起时窗口不可见：不推进相位也不重绘，避免后台空转
        if not self.isVisible():
            return
        self._phase += self.FRAME_MS / float(self.SWEEP_MS)
        if self._phase >= 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        radius = r.height() / 2
        charging = self._charging

        if self._unavailable:
            self._paint_unavailable(p, r, radius)
            p.end()
            return

        p.setPen(Qt.NoPen)
        p.setBrush(theme.charge_track_color() if charging else theme.track_color())
        p.drawRoundedRect(r, radius, radius)

        ratio = max(0.0, min(1.0, self._value / 100.0))
        if ratio > 0:
            w = max(r.height(), r.width() * ratio)
            fill = QRectF(r.left(), r.top(), w, r.height())
            if charging:
                self._paint_charge(p, fill, radius)
                self._paint_sweep(p, fill)
            else:
                p.setBrush(theme.ink_color())
                p.drawRoundedRect(fill, radius, radius)
        p.end()

    def _paint_unavailable(self, p: QPainter, r: QRectF, radius: float) -> None:
        """轨道 + 一条虚线：'这条设备没有可读的电量'。"""
        p.setPen(Qt.NoPen)
        p.setBrush(theme.track_color())
        p.drawRoundedRect(r, radius, radius)

        pen = QPen(theme.color(theme.TEXT_DIM))
        pen.setWidthF(1.0)
        pen.setDashPattern([1.6, 2.4])
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        y = r.center().y()
        p.drawLine(QPointF(r.left() + 2.5, y), QPointF(r.right() - 2.5, y))

    # ---------------- 充电形态 ----------------
    def _paint_charge(self, p: QPainter, fill: QRectF, radius: float) -> None:
        grad = QLinearGradient(fill.left(), 0.0, max(fill.left() + 1.0, fill.right()), 0.0)
        grad.setColorAt(0.0, theme.charge_deep_color())
        grad.setColorAt(1.0, theme.charge_color())
        p.setBrush(grad)
        p.drawRoundedRect(fill, radius, radius)

        # 前沿光点：随高光同步呼吸，低电量时也能看出"正在充"
        base = theme.charge_color()
        glow_r = fill.height() * 1.6
        cx, cy = fill.right(), fill.center().y()
        pulse = 0.5 + 0.5 * math.sin(self._phase * math.tau)
        halo = QRadialGradient(QPointF(cx, cy), glow_r)
        halo.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(),
                                    int(52 + 50 * pulse)))
        halo.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 0))
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

    def _paint_sweep(self, p: QPainter, fill: QRectF) -> None:
        """一道柔白高光在已填充段里从左滑到右，循环往复 = 向前充能。

        只裁在填充段内：高光跑出实心区域会被误读成"又涨了一截电量"。
        """
        band = max(26.0, fill.width() * 0.42)
        x = fill.left() - band + self._phase * (fill.width() + band)
        grad = QLinearGradient(x, 0.0, x + band, 0.0)
        grad.setColorAt(0.00, QColor(226, 255, 238, 0))
        grad.setColorAt(0.50, QColor(234, 255, 244, 152))
        grad.setColorAt(1.00, QColor(226, 255, 238, 0))

        clip = QPainterPath()
        clip.addRoundedRect(fill, fill.height() / 2, fill.height() / 2)
        p.save()
        p.setClipPath(clip)
        p.setBrush(grad)
        p.drawRoundedRect(
            QRectF(x, fill.top(), band, fill.height()),
            fill.height() / 2, fill.height() / 2,
        )
        p.restore()


class ToggleSwitch(QAbstractButton):
    """40x22 开关，带滑动动画。"""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        radius = r.height() / 2

        off = theme.track_color()
        on = theme.ink_color()
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
            int(off.alpha() + (on.alpha() - off.alpha()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, radius, radius)

        d = r.height() - 5
        x = 2.5 + (r.width() - d - 5) * t
        p.setBrush(theme.color(theme.ON_INK) if t > 0.5 else theme.color(theme.TEXT_DIM))
        p.drawEllipse(QRectF(x, 2.5, d, d))
        p.end()


class IconButton(QAbstractButton):
    """自绘图标按钮，自带 hover / press 反馈。

    refresh 按钮额外带"刷新完成"动效：
      点击即开始旋转 → 数据回来后停转、把对勾一笔画出来 → 停留 1s 淡出复位。
    这样点下去立刻有反馈，也不必靠猜数据有没有回来。
    """

    SPIN_MS = 860          # 一圈耗时
    MIN_SPIN_MS = 520      # 最短旋转时长：扫得太快时也让人看清在转
    CHECK_MS = 300         # 对勾描边时长
    HOLD_MS = 1000         # 对勾停留时长
    FADE_MS = 220          # 淡出时长
    STUCK_MS = 8000        # 兜底：扫描异常没回调时也不会永远转

    def __init__(self, shape: str, size: int = 26, icon_size: int = 15,
                 color: str = "", parent=None):
        super().__init__(parent)
        self.shape = shape
        self.icon_size = icon_size
        self.color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._spin = 0.0
        self._check = 0.0
        self._check_alpha = 1.0
        self._state = "idle"       # idle / spinning / done
        self._spin_started = 0.0

        # 不用 DeleteWhenStopped：动画对象被析构后 self._spin_anim 就成了悬空指针
        self._spin_anim = QPropertyAnimation(self, b"spin", self)
        self._spin_anim.setStartValue(0.0)
        self._spin_anim.setEndValue(360.0)
        self._spin_anim.setDuration(self.SPIN_MS)
        self._spin_anim.setEasingCurve(QEasingCurve.Linear)
        self._spin_anim.setLoopCount(-1)

        self._check_anim = QPropertyAnimation(self, b"check", self)
        self._check_anim.setDuration(self.CHECK_MS)
        self._check_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_anim = QPropertyAnimation(self, b"checkAlpha", self)
        self._fade_anim.setDuration(self.FADE_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.InQuad)
        self._fade_anim.finished.connect(self._to_idle)

    @property
    def active_color(self) -> str:
        return self.color or theme.TEXT_SUB

    def get_spin(self) -> float:
        return self._spin

    def set_spin(self, v: float) -> None:
        self._spin = v
        self.update()

    spin = Property(float, get_spin, set_spin)

    def get_check(self) -> float:
        return self._check

    def set_check(self, v: float) -> None:
        self._check = v
        self.update()

    check = Property(float, get_check, set_check)

    def get_check_alpha(self) -> float:
        return self._check_alpha

    def set_check_alpha(self, v: float) -> None:
        self._check_alpha = v
        self.update()

    checkAlpha = Property(float, get_check_alpha, set_check_alpha)

    # ---------------- 刷新动效 ----------------
    def start_spin(self) -> None:
        """开始旋转；已在转就保持，避免连点导致角度跳回 0。"""
        if self._state == "spinning":
            return
        import time

        self._state = "spinning"
        self._spin_started = time.monotonic()
        self._check = 0.0
        self._check_alpha = 1.0
        self._fade_anim.stop()
        self._check_anim.stop()
        self._spin_anim.stop()
        self._spin_anim.start()
        QTimer.singleShot(self.STUCK_MS, self._stuck_guard)
        self.update()

    def _stuck_guard(self) -> None:
        if self._state == "spinning":
            self.stop_spin()

    def finish(self) -> None:
        """数据回来了：停转并播放对勾。非旋转状态调用无副作用（自动刷新不会误触发）。"""
        if self._state != "spinning":
            return
        import time

        elapsed = (time.monotonic() - self._spin_started) * 1000
        delay = int(max(0.0, self.MIN_SPIN_MS - elapsed))
        if delay:
            QTimer.singleShot(delay, self._celebrate)
        else:
            self._celebrate()

    def stop_spin(self) -> None:
        """立即静止并复位（用于强制取消，不做完成动效）。"""
        self._spin_anim.stop()
        self._check_anim.stop()
        self._fade_anim.stop()
        self._state = "idle"
        self._spin = 0.0
        self._check = 0.0
        self._check_alpha = 1.0
        self.update()

    def _celebrate(self) -> None:
        if self._state != "spinning":
            return
        self._state = "done"
        self._spin_anim.stop()
        self._spin = 0.0
        self._check = 0.0
        self._check_alpha = 1.0
        self._check_anim.stop()
        self._check_anim.setStartValue(0.0)
        self._check_anim.setEndValue(1.0)
        self._check_anim.start()
        QTimer.singleShot(self.HOLD_MS, self._fade_out)

    def _fade_out(self) -> None:
        if self._state != "done":
            return
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._check_alpha)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _to_idle(self) -> None:
        self._state = "idle"
        self._spin = 0.0
        self._check = 0.0
        self._check_alpha = 1.0
        self.update()

    def mousePressEvent(self, e) -> None:
        # 点下去立刻起转，不等数据层的回调，避免"点了没反应"
        if self.shape == "refresh":
            self.start_spin()
        super().mousePressEvent(e)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.hover_color())
            p.drawRoundedRect(r, 7, 7)

        color = theme.TEXT if self._hover else self.active_color
        side = float(self.icon_size)
        box = QRectF((r.width() - side) / 2, (r.height() - side) / 2, side, side)
        if self.shape == "refresh":
            if self._state == "done":
                p.setOpacity(max(0.0, min(1.0, self._check_alpha)))
                icons.draw_check(p, box, color, 2.0, self._check)
                p.setOpacity(1.0)
            else:
                if self._state == "spinning":
                    p.translate(r.center())
                    p.rotate(self._spin)
                    p.translate(-r.center())
                icons.draw_refresh(p, box, color, 1.5)
        elif self.shape == "gear":
            icons.draw_gear(p, box, color, 1.5)
        elif self.shape == "close":
            icons.draw_close(p, box, color, 1.6)
        p.end()


class ElidedLabel(QLabel):
    """超长文本自动省略，避免挤压右侧电量。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = self.fontMetrics()
        avail = max(10, self.width() - 2)
        elided = metrics.elidedText(self._full, Qt.ElideRight, avail)
        if elided != super().text():
            super().setText(elided)

    def full_text(self) -> str:
        return self._full


class DeviceIconTile(QWidget):
    """设备图标磁贴：淡墨底 + 线性图标。"""

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self.device = device
        self.setFixedSize(34, 34)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())

        path = QPainterPath()
        path.addRoundedRect(r, 11, 11)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.ink_soft_color())
        p.drawPath(path)

        icons.draw_kind(p, self.device.kind, r.adjusted(7, 7, -7, -7),
                        theme.TEXT, 1.4)
        p.end()


class BoltBadge(QWidget):
    """充电状态小闪电，替代"充电中"这类多余文字。

    几何：字形 20px + 四周各 2px，总宽 24px —— 光晕要外扩，得留出扩散余量，
    否则呼吸到最亮的一帧会被控件边界切出一条直边。
    动效：外圈同色柔光按 2.4s 正弦缓慢起伏（半径与透明度同步），视觉上就是
    一圈"能量在一呼一吸"，不用写"充电中"也能看出状态。
    """

    GLYPH = 20           # 闪电字形盒
    PAD = 2              # 光晕扩散余量
    BREATH_MS = 2400     # 一次完整呼吸（暗 → 亮 → 暗）
    FRAME_MS = 40        # 25fps：光晕是慢变量，再密也看不出差别，白烧 CPU

    def __init__(self, parent=None):
        super().__init__(parent)
        self.SIZE = self.GLYPH + self.PAD * 2
        self.setFixedSize(self.SIZE, self.SIZE)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        # 只有真被显示出来（= 正在充电）才起呼吸，隐藏时不占 CPU
        super().showEvent(event)
        self._phase = 0.0
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        self._phase = 0.0
        super().hideEvent(event)

    def _tick(self) -> None:
        # 卡片收起时窗口不可见：不推进相位也不重绘，后台零成本
        if not self.isVisible():
            return
        self._phase += self.FRAME_MS / float(self.BREATH_MS)
        if self._phase >= 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        center = r.center()

        base = theme.charge_bolt_color()
        # 正弦呼吸量：0 = 最暗最小，1 = 最亮最大
        wave = 0.5 - 0.5 * math.cos(self._phase * math.tau)

        # 最大半径恰好等于控件半宽，渐变到边界时 alpha 已归零，不会露出切边
        halo_r = r.width() * (0.35 + 0.15 * wave)
        a0 = int(44 + 54 * wave)
        halo = QRadialGradient(center, halo_r)
        halo.setColorAt(0.00, QColor(base.red(), base.green(), base.blue(), a0))
        halo.setColorAt(0.55, QColor(base.red(), base.green(), base.blue(), int(a0 * 0.34)))
        halo.setColorAt(1.00, QColor(base.red(), base.green(), base.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, halo_r, halo_r)

        glyph = QRectF(center.x() - self.GLYPH / 2,
                       center.y() - self.GLYPH / 2,
                       float(self.GLYPH), float(self.GLYPH))
        # 字形也随呼吸轻微提亮，光晕和本体才像同一个光源
        p.setOpacity(0.90 + 0.10 * wave)
        icons.draw_bolt(p, glyph, theme.CHARGE_BOLT)
        p.setOpacity(1.0)
        p.end()


class PercentLabel(QWidget):
    """自绘百分比：大号数字 + 小号单位，共享基线、右边缘严格齐平。

    用两个 QLabel 拼会因为字号不同导致 % 下沉、右边缘参差，这里统一手绘。
    """

    NUMBER_PX = 19
    UNIT_PX = 10
    WIDTH = 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = "--"
        self._unit = ""
        self.setFixedSize(self.WIDTH, 26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._num_font = QFont(theme.FONT_NUM)
        self._num_font.setPixelSize(self.NUMBER_PX)
        self._num_font.setWeight(QFont.Bold)
        self._num_font.setLetterSpacing(QFont.PercentageSpacing, 98.0)
        self._unit_font = QFont(theme.FONT)
        self._unit_font.setPixelSize(self.UNIT_PX)
        self._unit_font.setWeight(QFont.DemiBold)

    def set_value(self, text: str, unit: str = "%") -> None:
        self._text = text
        self._unit = unit if text != "--" else ""
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        num_metrics = QFontMetricsF(self._num_font)
        unit_metrics = QFontMetricsF(self._unit_font)
        num_w = num_metrics.horizontalAdvance(self._text)
        unit_w = unit_metrics.horizontalAdvance(self._unit) if self._unit else 0.0
        gap = 1.0 if unit_w else 0.0
        total = num_w + gap + unit_w

        x = self.width() - total
        baseline = (self.height() + num_metrics.ascent() - num_metrics.descent()) / 2

        p.setFont(self._num_font)
        p.setPen(theme.color(theme.TEXT))
        p.drawText(QPointF(x, baseline), self._text)

        if unit_w:
            p.setFont(self._unit_font)
            p.setPen(theme.color(theme.TEXT_SUB))
            p.drawText(QPointF(x + num_w + gap, baseline), self._unit)
        p.end()


class DeviceRow(QFrame):
    """单个外设一行：图标 + 名称与百分比同线 + 通栏电量条。

    行本身不可点击，所以不做任何 hover 反馈 —— 有反馈反而让人以为能点。
    """

    def __init__(self, device: Device, animate: bool = True, parent=None):
        super().__init__(parent)
        self.device = device
        self._animate = animate
        self.setFixedHeight(44)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(11)

        self.tile = DeviceIconTile(device)
        lay.addWidget(self.tile, 0, Qt.AlignVCenter)

        # 名称行 + 电量条包进一个固定高度的块，再整体垂直居中。
        # 直接往行里塞嵌套布局的话，多出来的高度会被名称行吃掉，
        # 名称被顶到下面、电量条贴到行底，看起来就是"电量显示太靠下"。
        block = QWidget()
        block.setFixedHeight(37)
        mid = QVBoxLayout(block)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(7)

        line = QHBoxLayout()
        line.setSpacing(4)
        line.setContentsMargins(0, 0, 0, 0)
        self.name_label = ElidedLabel(device.name)
        self.name_label.setObjectName("DevName")
        line.addWidget(self.name_label, 1)
        self.bolt = BoltBadge()
        line.addWidget(self.bolt, 0, Qt.AlignVCenter)
        self.pct_label = PercentLabel()
        line.addWidget(self.pct_label, 0, Qt.AlignVCenter)
        mid.addLayout(line)

        self.bar = BatteryBar()
        mid.addWidget(self.bar)
        lay.addWidget(block, 1, Qt.AlignVCenter)

        self.apply(device, animate)

    def apply(self, device: Device, animate: bool = True) -> None:
        self.device = device
        charging = bool(device.charging)
        # "设备在、但固件不给电量" —— 与"暂时没读到"是两回事，视觉上要区分
        unavailable = (device.level is None
                       and (device.raw or {}).get("state") == "无电量接口")
        self.name_label.setText(device.name)
        self.pct_label.set_value(device.percent_text)
        self.bolt.setVisible(charging)
        self.bar.set_unavailable(unavailable)
        self.bar.set_level(device.level, animate)
        self.bar.set_charging(charging and not unavailable)
        self.tile.device = device
        self.tile.update()
