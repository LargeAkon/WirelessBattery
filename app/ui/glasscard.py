# -*- coding: utf-8 -*-
"""毛玻璃卡片容器：模糊背板 + 霜化白层 + 边缘高光 + 极细颗粒。

材质配方参考 iOS 的 `systemMaterialLight`（不是 macOS 那种浓灰玻璃）：

    背景（已提亮、已加饱和度、真正糊开）
      ↓ 叠一层薄白霜化层（60% 左右，上下有极淡渐变）
      ↓ 左上到右下的一道柔光（让玻璃有"面"，不是一块平色）
      ↓ 1px 亮边 + 1px 内壁反光（玻璃的"壁"）
      ↓ 极细颗粒（磨砂手感，几乎看不见）

之前的两个错误方向：
  · 遮罩加到 72%~96% → 背景被彻底盖住，成了实心白板；
  · 底图降饱和度 → 壁纸的颜色被抽成灰，玻璃永远"脏"。
现在靠"糊得干净 + 颜色泛上来 + 薄白层"出质感。

拿不到屏幕影像时退回不透明底色（宁可朴素，也不要"半透明却没糊"的廉价感）。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QLinearGradient, QPainter, QPainterPath,
    QPainterPathStroker, QPen, QPixmap,
)
from PySide6.QtWidgets import QWidget

import theme
from ui.glass import ScreenBlur

RADIUS = 20.0

# ---- 浅色材质（可调参数集中在这里）----
LIGHT_VEIL = 0.84        # 霜化层基础不透明度。再薄的话，背后窗口会剩一块矩形
LIGHT_VEIL_DARK_ADD = 0.08  # 底图越暗，霜化层额外加厚多少
LIGHT_TOP = 0.18         # 顶部额外白，形成上亮下暗的厚度
LIGHT_FOOT = 18          # 底部一点冷灰，压出"玻璃有厚度"的收口
LIGHT_SHEEN = 40         # 对角柔光
LIGHT_GRAIN = 0.24       # 颗粒强度（磨砂手感，太轻就成了塑料板）

# ---- 深色材质 ----
DARK_VEIL = 0.62
DARK_TOP = 26
DARK_SHEEN = 16
DARK_INNER = 34
DARK_GRAIN = 0.26

_NOISE: QPixmap | None = None


def _noise_tile() -> QPixmap:
    """96×96 噪点，只生成一次。

    纯色玻璃（尤其是浅色主题盖在白色页面上）看起来就是一块白板，
    加一层几乎看不见的颗粒才有"磨砂材质"的手感，成本也只有一次平铺。

    这里刻意不用 random：random 会连带 hashlib，而 hashlib 又把 5MB 的
    OpenSSL 拖进安装包。只为生成一张噪点图不值这个代价，所以自己算一遍
    线性同余，结果确定、每次一样。
    """
    global _NOISE
    if _NOISE is not None:
        return _NOISE

    state = [20261120]

    def nxt(limit: int) -> int:
        state[0] = (state[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return (state[0] >> 8) % limit

    size = 96
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    for y in range(size):
        for x in range(size):
            v = 0 if nxt(2) == 0 else 255
            img.setPixelColor(x, y, QColor(v, v, v, nxt(38)))
    _NOISE = QPixmap.fromImage(img)
    return _NOISE


class GlassCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.blur: ScreenBlur | None = None
        self.enabled = True

    def attach(self, blur: ScreenBlur | None) -> None:
        self.blur = blur
        self.update()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        dark = theme.current_mode() == "dark"
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)

        painted = False
        if self.enabled and self.blur is not None and self.blur.ready:
            p.save()
            p.setClipPath(path)
            p.setPen(Qt.NoPen)
            painted = self.blur.paint(
                p, QRectF(self.rect()),
                QRect(self.mapToGlobal(QPoint(0, 0)), self.size()),
            )
            p.restore()

        p.setPen(Qt.NoPen)
        if not painted:
            p.setBrush(theme.color(theme.BG))
            p.drawPath(path)
        else:
            # 1) 霜化层：一层薄白，把底图变成"白蒙蒙"的玻璃。
            #    浅色材质按底图亮度微调厚度：暗背景盖厚一点才不会透出黑灰，
            #    亮背景盖薄一点才留得住背后的明暗与色晕（固定厚度两头都做不好）。
            t = max(0.0, min(1.0, (self.blur.brightness if self.blur else 128.0) / 255.0))
            tint = QColor(theme.color(theme.CARD_FILL))
            if dark:
                tint.setAlphaF(DARK_VEIL)
            else:
                tint.setAlphaF(LIGHT_VEIL + LIGHT_VEIL_DARK_ADD * (1.0 - t))
            p.setBrush(tint)
            p.drawPath(path)

            p.save()
            p.setClipPath(path)

            # 2) 厚度渐变：上沿亮、下沿略沉，玻璃才有体积
            grad = QLinearGradient(0, 0, 0, self.height())
            if dark:
                grad.setColorAt(0.0, QColor(255, 255, 255, DARK_TOP))
                grad.setColorAt(0.45, QColor(255, 255, 255, 0))
                grad.setColorAt(1.0, QColor(0, 0, 0, DARK_INNER))
            else:
                # 上亮下暗才是玻璃的"体积"；下沿如果也提亮，白底上就成了一块白纸
                grad.setColorAt(0.0, QColor(255, 255, 255, int(255 * LIGHT_TOP)))
                grad.setColorAt(0.40, QColor(255, 255, 255, 0))
                grad.setColorAt(1.0, QColor(196, 201, 211, LIGHT_FOOT))
            p.setBrush(grad)
            p.drawRect(self.rect())

            # 3) 对角柔光：左上到右下的一道极淡白光
            sheen = QLinearGradient(0, 0, self.width(), self.height())
            sheen.setColorAt(0.0, QColor(255, 255, 255, DARK_SHEEN if dark else LIGHT_SHEEN))
            sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
            p.setBrush(sheen)
            p.drawRect(self.rect())

            # 4) 内壁阴影。只在深色画这一圈：浅色卡片又矮又宽，
            #    描边环的内沿会剩一块发灰的长方形，看起来像透出了背后的窗口。
            if dark:
                inner = QPainterPath()
                inner.addRoundedRect(body.adjusted(8, 8, -8, -8),
                                     max(2.0, RADIUS - 8), max(2.0, RADIUS - 8))
                stroker = QPainterPathStroker()
                stroker.setWidth(22.0)
                band = stroker.createStroke(inner).intersected(path)
                shade = QLinearGradient(0, 0, 0, self.height())
                shade.setColorAt(0.0, QColor(255, 255, 255, 14))
                shade.setColorAt(0.55, QColor(0, 0, 0, int(DARK_INNER * 0.6)))
                shade.setColorAt(1.0, QColor(0, 0, 0, int(DARK_INNER * 0.9)))
                p.setPen(Qt.NoPen)
                p.setBrush(shade)
                p.drawPath(band)

            # 5) 颗粒：磨砂手感，浅色主题要非常克制，重了就"脏"
            p.setOpacity(DARK_GRAIN if dark else LIGHT_GRAIN)
            p.drawTiledPixmap(self.rect(), _noise_tile())
            p.setOpacity(1.0)

            p.restore()

        # 6) 顶部内高光：贴着上边缘的一道亮线，玻璃的标志性特征
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.NoPen)
        hi = QLinearGradient(0, 0, 0, 2.5)
        hi.setColorAt(0.0, QColor(255, 255, 255, 96 if dark else 225))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hi)
        p.drawRect(QRectF(0.0, 0.5, float(self.width()), 2.5))
        p.restore()

        # 7) 描边：浅色主题用淡墨线，纯白描边在白卡片上等于没边框
        pen = QPen(theme.color(theme.CARD_STROKE))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # 8) 内壁反光：紧贴边框的一道细白，玻璃的边缘必须是"亮"的
        if not dark:
            wall_pen = QPen(QColor(255, 255, 255, 165))
            wall_pen.setWidthF(1.0)
            p.setPen(wall_pen)
            wall = QPainterPath()
            wall.addRoundedRect(body.adjusted(1.4, 1.4, -1.4, -1.4),
                                RADIUS - 1.4, RADIUS - 1.4)
            p.drawPath(wall)
        p.end()
