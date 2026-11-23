# -*- coding: utf-8 -*-
"""矢量图标绘制（无外部资源，随分辨率清晰缩放）。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from model import MOUSE, KEYBOARD, HEADSET


def _pen(color: str, width: float) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def draw_kind(p: QPainter, kind: str, rect: QRectF, color: str, width: float = 1.45) -> None:
    """在 rect 内绘制设备类型图标（24x24 逻辑网格等比缩放）。"""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    side = min(rect.width(), rect.height())
    scale = side / 24.0
    p.translate(rect.center())
    p.scale(scale, scale)
    p.translate(-12, -12)
    p.setPen(_pen(color, width))

    if kind == MOUSE:
        body = QPainterPath()
        body.moveTo(12, 2.8)
        body.cubicTo(8.6, 2.8, 6.8, 6.0, 6.8, 9.6)
        body.lineTo(6.8, 15.4)
        body.cubicTo(6.8, 19.4, 9.0, 21.4, 12, 21.4)
        body.cubicTo(15.0, 21.4, 17.2, 19.4, 17.2, 15.4)
        body.lineTo(17.2, 9.6)
        body.cubicTo(17.2, 6.0, 15.4, 2.8, 12, 2.8)
        p.drawPath(body)
        p.drawLine(QPointF(12, 3.4), QPointF(12, 8.0))
        p.drawLine(QPointF(6.9, 9.0), QPointF(17.1, 9.0))

    elif kind == KEYBOARD:
        p.drawRoundedRect(QRectF(2.2, 7.0, 19.6, 10.0), 2.4, 2.4)
        for i in range(5):
            x = 5.0 + i * 3.5
            p.drawPoint(QPointF(x, 10.4))
        for i in range(4):
            x = 6.8 + i * 3.5
            p.drawPoint(QPointF(x, 13.2))
        p.drawLine(QPointF(8.6, 15.6), QPointF(15.4, 15.6))

    elif kind == HEADSET:
        band = QPainterPath()
        band.moveTo(4.2, 13.6)
        band.lineTo(4.2, 11.8)
        band.cubicTo(4.2, 6.7, 7.6, 3.4, 12.0, 3.4)
        band.cubicTo(16.4, 3.4, 19.8, 6.7, 19.8, 11.8)
        band.lineTo(19.8, 13.6)
        p.drawPath(band)
        p.drawRoundedRect(QRectF(2.2, 12.4, 4.2, 7.4), 2.1, 2.1)
        p.drawRoundedRect(QRectF(17.6, 12.4, 4.2, 7.4), 2.1, 2.1)

    else:  # 通用外设
        p.drawRoundedRect(QRectF(3.8, 5.6, 16.4, 12.8), 3.6, 3.6)
        p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
        p.drawLine(QPointF(12, 7.6), QPointF(12, 9.6))
        p.drawLine(QPointF(12, 14.4), QPointF(12, 16.4))

    p.restore()


def draw_bolt(p: QPainter, rect: QRectF, color: str) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center())
    p.scale(scale, scale)
    p.translate(-12, -12)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    path.moveTo(13.6, 2.6)
    path.lineTo(6.4, 13.4)
    path.lineTo(11.2, 13.4)
    path.lineTo(10.0, 21.4)
    path.lineTo(17.6, 10.2)
    path.lineTo(12.6, 10.2)
    path.closeSubpath()
    p.drawPath(path)
    p.restore()


def draw_refresh(p: QPainter, rect: QRectF, color: str, width: float = 1.6) -> None:
    from math import cos, radians, sin

    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center())
    p.scale(scale, scale)
    p.translate(-12, -12)
    p.setPen(_pen(color, width))
    arc = QRectF(4.6, 4.6, 14.8, 14.8)
    path = QPainterPath()
    path.arcMoveTo(arc, 75)
    path.arcTo(arc, 75, 285)
    p.drawPath(path)
    ang = radians(75)
    tip = QPointF(arc.center().x() + arc.width() / 2 * cos(ang),
                  arc.center().y() - arc.height() / 2 * sin(ang))
    p.drawLine(tip, QPointF(tip.x() - 2.6, tip.y() - 2.4))
    p.drawLine(tip, QPointF(tip.x() + 2.2, tip.y() - 2.6))
    p.restore()


def draw_check(p: QPainter, rect: QRectF, color: str, width: float = 1.9,
               progress: float = 1.0) -> None:
    """对勾：按 progress 0→1 从短边画到长边，用于"刷新完成"的动效。"""
    from math import hypot

    if progress <= 0.001:
        return
    k = max(0.0, min(1.0, float(progress)))
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / 24.0
    # 轻微弹入：起笔时略小，随即回到原尺寸
    zoom = 0.86 + 0.14 * min(1.0, k * 1.6)
    p.translate(rect.center())
    p.scale(scale * zoom, scale * zoom)
    p.translate(-12, -12)
    p.setPen(_pen(color, width))
    p.setBrush(Qt.NoBrush)

    a = QPointF(5.2, 12.6)
    b = QPointF(10.2, 17.6)
    c = QPointF(19.0, 6.6)
    len1 = hypot(b.x() - a.x(), b.y() - a.y())
    len2 = hypot(c.x() - b.x(), c.y() - b.y())
    drawn = (len1 + len2) * k

    path = QPainterPath(a)
    if drawn <= len1:
        t = drawn / len1
        path.lineTo(QPointF(a.x() + (b.x() - a.x()) * t,
                            a.y() + (b.y() - a.y()) * t))
    else:
        path.lineTo(b)
        t = min(1.0, (drawn - len1) / len2)
        path.lineTo(QPointF(b.x() + (c.x() - b.x()) * t,
                            b.y() + (c.y() - b.y()) * t))
    p.drawPath(path)
    p.restore()


def draw_gear(p: QPainter, rect: QRectF, color: str, width: float = 1.6) -> None:
    """设置图标：滑杆样式，小尺寸下比齿轮更清晰。"""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center())
    p.scale(scale, scale)
    p.translate(-12, -12)
    rows = ((6.6, 9.0), (12.0, 15.2), (17.4, 7.2))
    for y, knob_x in rows:
        p.setPen(_pen(color, width))
        p.drawLine(QPointF(3.8, y), QPointF(20.2, y))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(knob_x, y), 2.1, 2.1)
    p.restore()


def draw_close(p: QPainter, rect: QRectF, color: str, width: float = 1.8) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center())
    p.scale(scale, scale)
    p.translate(-12, -12)
    p.setPen(_pen(color, width))
    p.drawLine(QPointF(7.5, 7.5), QPointF(16.5, 16.5))
    p.drawLine(QPointF(16.5, 7.5), QPointF(7.5, 16.5))
    p.restore()


# ---------------- 应用图标 ----------------
# 深色圆角方块 + 白色电池：窗口图标、任务栏图标、app.ico 共用这一张。
# 与托盘图标不同，这里尺寸大（16~256），可以用超采样 + 平滑缩回换取圆角质量；
# 托盘图标 16px 必须整像素直绘，不能共用同一套几何。
_APP_BG = "#0A0B0C"
_APP_FG = "#FFFFFF"


def app_icon(size: int = 256) -> QPixmap:
    """应用图标：返回 size×size 的 QPixmap（透明外缘）。"""
    size = max(16, int(size))
    # 小尺寸多超采样一点，256 用 2x 已足够（再高只是白烧时间）
    ss = 4 if size <= 96 else 2
    px = size * ss
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = float(px)

    # 底板：圆角方块，留一点透明边距，避免贴边被系统裁掉圆角
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_APP_BG))
    inset = s * 0.028
    p.drawRoundedRect(QRectF(inset, inset, s - 2 * inset, s - 2 * inset),
                      s * 0.232, s * 0.232)

    # 电池：宽扁机身 + 右侧正极，整体居中
    body_w, body_h = s * 0.585, s * 0.330
    tip_w = s * 0.048
    total = body_w + tip_w
    x = (s - total) / 2.0
    y = (s - body_h) / 2.0
    body = QRectF(x, y, body_w, body_h)
    radius = body_h * 0.32
    tip_h = body_h * 0.44
    tip = QRectF(body.right(), y + (body_h - tip_h) / 2.0, tip_w, tip_h)

    wall = max(1.0, body_h * 0.170)
    inner = body.adjusted(wall, wall, -wall, -wall)
    inner_r = max(0.5, radius - wall)

    # 机身与正极一次画成实心，再挖内腔 —— 描边压在路径中心会发虚
    p.setBrush(QColor(_APP_FG))
    p.drawRoundedRect(body, radius, radius)
    p.drawRoundedRect(tip, min(tip_w, tip_h) / 2.0, min(tip_w, tip_h) / 2.0)

    # 内腔：直接用底板色覆盖（不能用 Clear —— 会把底板也挖成透明洞，
    # 图标放进浅色任务栏就是一块白斑）
    p.setBrush(QColor(_APP_BG))
    p.drawRoundedRect(inner, inner_r, inner_r)

    # 内腔左侧填一段白（约 58%），右侧留空，读作"电量图标"
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_APP_FG))
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(inner, inner_r, inner_r)
    p.setClipPath(clip)
    p.drawRect(QRectF(inner.left(), inner.top(),
                      inner.width() * 0.58, inner.height()))
    p.restore()
    p.end()

    if ss != 1:
        pm = pm.scaled(size, size, Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation)
    return pm


# ---------------- 托盘图标 ----------------
# 造型：经典电池轮廓 —— 一圈线 + 内腔里一段实心填充，右侧接一枚小正极。
#
# 为什么回到"描边 + 内腔"：上一版做成"两段式实心"（充到的是实心、没充到的是
# 半透明），躯干 13x11 接近正方形，电量一高整块就糊成一个方块，看着像奶瓶。
# 轮廓款在 16px 里能明确给出"这是一节电池"的信号，而且宽扁的比例（约 1.9:1）
# 一眼就是电池，不是瓶子。
#
# 三处必须像素对齐，否则 16px 下会发灰：
# 1) 外壳、内腔、正极的坐标全部 round() 到整像素；
# 2) 壳体厚度取整（16px 下 1px、24px 下 2px），描边才不会摊在半个像素上；
# 3) 不用 QPen 描边（描边以路径为中心，必然压在半像素），改成
#    "填满外轮廓 + 挖掉内腔"，直角边正好落在整像素边界。
_TIP_W_RATIO = 0.080    # 正极宽度（16px 下 1px、24px 下 2px、32px 下 3px）
# 正极直接贴在主体上，不留缝。留 1px 缝在 16px 下会让正极变成一粒飘着的小点，
# 而且"电池和电极之间断开"本身就不像电池（参考图里的缝是 36px 高时才成立的比例）。
_GAP = 0.0
_TIP_H_RATIO = 0.42      # 正极高度（相对电池高度）
# 机身宽高比。**这是"图标小/扁"的真正开关**：以前按"占画布高度的比例"取值
# （0.5 → 16px 下只有 8px 高），横向撑满、纵向只占一半，于是又小又扁。
# Windows 托盘槽就是 16px，画不出界，想变大只能吃上下留白。
# 现在改成由宽度反推高度：16px → 15×12（占画布 75%），24px → 22×18，
# 32px → 31×24，各尺寸比例一致，不再出现某个 DPI 下突然变扁。
# 横置电池的"扁"感由内腔比例撑住（16px 内腔 11×8），外形不必再压扁。
_BODY_ASPECT = 1.25
# 0.30 在高 12px 的机身下圆角近 4px，整个图标像胶囊；0.24 收成 3px 才像电池硬壳。
_BODY_R_RATIO = 0.24     # 外圆角（相对电池高度）
# 壳体厚度：原来 1px 在 16px 里只剩"一根线"，远看发虚。
# 16px 用 2px 后横向占 1/8 画布，视觉重量够了，内腔还有 11×8 放填充。
# 取 0.095 而不是 0.105：后者在 24px 会跳到 3px，壁厚显得比 16px 还粗。
_WALL_RATIO = 0.095

_MIN_FILL_PX = 2.0       # 最小填充宽度：1px 会被左侧圆角吃掉，看不出"有电"


def _tray_geometry(s: float) -> tuple[QRectF, QRectF, QRectF, float, float]:
    """返回 (外轮廓, 内腔, 正极, 外圆角, 内腔圆角)，全部对齐整像素。"""
    tip_w = max(1.0, float(round(s * _TIP_W_RATIO)))
    gap = _GAP
    # 主体从最左边铺到正极缝隙处 —— 16px 里每一像素都要用上
    w = s - tip_w - gap
    h = max(4.0, float(round(w / _BODY_ASPECT)))
    # 高度与画布同奇偶，(s-h) 才是偶数，上下留白相等、y 落在整像素
    if int(h) % 2 != int(s) % 2:
        h -= 1.0
    h = min(h, s)
    y = float(round((s - h) / 2))
    outer = QRectF(0.0, y, w, h)

    wall = max(1.0, float(round(s * _WALL_RATIO)))
    # 内腔绝不能窄到没有：窄了填充块就变成一条线，等于白做
    wall = min(wall, max(1.0, (h - 3.0) / 2))

    tip_h = max(2.0, float(round(h * _TIP_H_RATIO)))
    tip = QRectF(outer.right() + gap,
                 float(round(y + (h - tip_h) / 2)),
                 tip_w, tip_h)

    radius = max(1.0, float(round(h * _BODY_R_RATIO)))
    radius = min(radius, h / 2.0)
    return outer, outer.adjusted(wall, wall, -wall, -wall), tip, radius, \
        max(1.0, radius - wall)


def _canvas(size: int, dpr: float) -> tuple[QPixmap, QPainter, float, float]:
    """按设备像素建画布，直接以目标分辨率绘制。

    两个要点：
    1) 不再"4 倍超采样 + 平滑缩回"——那等于把每条边摊到 2~3 个像素上，
       16px 里必然糊。一次画到位。
    2) dpr 只在画完之后 setDevicePixelRatio 打标记，绘制全程用设备像素坐标。
       若一开始就设 dpr，QPainter 会按逻辑像素缩放，round() 出来的"整像素"
       其实是设备像素的一半 —— 200% 缩放下图标会被放大两倍再裁掉一半。
    """
    px = max(8, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    return pm, p, float(px), float(dpr)


def _finish(pm: QPixmap, p: QPainter, dpr: float) -> QPixmap:
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _paint_shell(p: QPainter, s: float, ink: str) -> tuple[QRectF, float]:
    """画轮廓（外轮廓填满 + 挖空内腔）与正极，返回 (内腔矩形, 内腔圆角)。"""
    outer, inner, tip, radius, inner_radius = _tray_geometry(s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ink))
    p.drawRoundedRect(outer, radius, radius)

    r = min(tip.width(), tip.height()) / 2.0
    p.drawRoundedRect(tip, r, r)

    # 挖出内腔：直角边压在整像素上，只有圆角走抗锯齿
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.setBrush(Qt.black)
    p.drawRoundedRect(inner, inner_radius, inner_radius)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.setBrush(QColor(ink))
    return inner, inner_radius


def _inner_path(inner: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(inner, radius, radius)
    return path


def tray_pixmap(level: float | None, ink: str, size: int = 16,
                dpr: float = 1.0) -> QPixmap:
    """单块电池：内腔里的实心块长度 = 该电量。"""
    canvas, p, s, dpr = _canvas(size, dpr)
    inner, inner_radius = _paint_shell(p, s, ink)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ink))
    if level is None:
        # 未知电量：内腔正中一个小方块，区别于 0%（空）与满电
        dot = max(2.0, float(round(s * 0.10)))
        p.drawRect(QRectF(round(inner.center().x() - dot / 2),
                          round(inner.center().y() - dot / 2), dot, dot))
    else:
        ratio = max(0.0, min(1.0, float(level) / 100.0))
        if ratio > 0.02:
            # 严格按比例取整：若按"某个最小高度"兜底，12% 和 48% 会画成
            # 一模一样长的一截，图标就失去意义了。
            w = min(inner.width(),
                    max(_MIN_FILL_PX, float(round(inner.width() * ratio))))
            p.save()
            p.setClipPath(_inner_path(inner, inner_radius))
            p.drawRect(QRectF(inner.left(), inner.top(), w, inner.height()))
            p.restore()
    return _finish(canvas, p, dpr)


# 托盘会请求的尺寸：Windows 在 100%~200% 缩放下给 16 / 20 / 24 / 32，
# 40 / 48 是 250% 以上的兜底。每个尺寸再补一份 2x 位图（带 devicePixelRatio），
# Qt 直接挑最接近的那张，不做插值 —— 插值才是"糊"的真正来源。
_TRAY_SIZES = (16, 20, 24, 32, 40, 48)
_TRAY_DPRS = (1.0, 2.0)


def _build_icon(builder) -> QIcon:
    icon = QIcon()
    for size in _TRAY_SIZES:
        for dpr in _TRAY_DPRS:
            icon.addPixmap(builder(size, dpr))
    return icon


def tray_icon(level: float | None, ink: str) -> QIcon:
    """静态托盘图标（多尺寸 + 双 DPR，系统按需原生取用，不做插值）。"""
    return _build_icon(lambda s, d: tray_pixmap(level, ink, s, d))


# 充电态：QSystemTrayIcon 只吃静态位图，没法真做动画，所以预先渲染若干帧、
# 由调用方定时轮换。轮换只是换一张画好的图，CPU 几乎为零。
# 动画语义：内腔里的绿色像电量一样**从左往右涨满**（0 → 100%），涨满停两帧再从头来。
# 不做"一段绿色横向滑动"——那是"液体在流"，看不出充进去了；从左往右填满才读作充电。
CHARGE_STEPS = 12      # 从空到满的帧数（16px 内腔 11px，正好每帧涨 1 像素）
CHARGE_HOLD = 2        # 涨满后多停两帧，避免刚满就闪回空


def _tray_charge_pixmap(ink: str, charge_ink: str, size: int,
                        dpr: float, t: float) -> QPixmap:
    """充电帧：外壳保持原色，内腔里的绿色从左侧按 t∈[0,1] 涨到满。"""
    canvas, p, s, dpr = _canvas(size, dpr)
    inner, inner_radius = _paint_shell(p, s, ink)
    if inner.width() <= 1 or inner.height() <= 1:
        return _finish(canvas, p, dpr)

    k = max(0.0, min(1.0, float(t)))
    w = min(inner.width(), float(round(inner.width() * k)))
    if w > 0:
        p.save()
        p.setClipPath(_inner_path(inner, inner_radius))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(charge_ink))
        p.drawRect(QRectF(inner.left(), inner.top(), w, inner.height()))
        p.restore()
    return _finish(canvas, p, dpr)


def tray_charge_frames(ink: str, charge_ink: str,
                       steps: int = CHARGE_STEPS,
                       hold: int = CHARGE_HOLD) -> list[QIcon]:
    """充电帧：绿色从空涨到满，停留 hold 帧后循环。"""
    steps = max(2, int(steps))
    total = steps + max(0, int(hold))
    frames = []
    for i in range(total):
        t = min(1.0, i / (steps - 1))
        frames.append(_build_icon(
            lambda s, d, k=t: _tray_charge_pixmap(ink, charge_ink, s, d, k)))
    return frames
