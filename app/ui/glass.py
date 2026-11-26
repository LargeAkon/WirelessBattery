# -*- coding: utf-8 -*-
"""毛玻璃背景：抓一张屏幕、把背后那块糊掉，再当卡片底图。

为什么不用 DWM 的 Acrylic：实测 SetWindowCompositionAttribute 在本机
（Win11）只给到一层染色，没有真实模糊，且模糊区域是整个窗口矩形，
圆角外会露出方形光晕。自己抓屏模糊则可以精确裁进圆角、不影响阴影，
观感更接近 macOS / iOS 的材质。

材质配方（关键，之前的版本走了弯路）：
  1. 先把底图缩小到 1/5，再用 QGraphicsBlurEffect 做真高斯模糊。
     早期版本用「缩到 1/11 再双线性放大」冒充模糊：那本质上是把每 11×11
     个像素取均值后拉平，文字、表格线糊不掉，还会留下方格状的斑块——
     看着脏、看着廉价，跟苹果材质差得最远的一点就在这里。
  2. 提亮（gamma 抬暗部），但保留明暗结构，不能混白压平。
  3. **提高饱和度**再混合。苹果的 vibrancy 是让壁纸的颜色透上来泛彩，
     不是抽成灰——降饱和度是"脏玻璃"的直接成因，这是本文件旧版最大的错误。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QScreen
from PySide6.QtWidgets import (
    QApplication, QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene,
)

# 材质参数：抓屏后统一处理，深浅主题共用同一张底图
SATURATE = 1.42     # 饱和度倍数（>1 泛彩，<1 发灰）
LIFT = 0.82         # gamma 提亮（<1 变亮，只抬暗部）
DOWNSCALE = 6       # 先缩到 1/6，再对这张小图做高斯
BLUR_PX = 4.0       # 小图上的半径，等效到屏幕约 DOWNSCALE/2 + BLUR_PX*DOWNSCALE ≈ 27px


def _grade(img: QImage, lift: float | None = None,
           saturate: float | None = None) -> QImage:
    """一次遍历完成提亮 + 饱和度调整。

    `QImage.bits()` 拿的是可写 memoryview，比 setPixelColor 快两个数量级；
    只在缩小后的缩略图上跑，几十毫秒。
    """
    # 参数默认取模块常量（运行时读取，方便整体调材质，也方便单独覆盖）
    lift = LIFT if lift is None else lift
    saturate = SATURATE if saturate is None else saturate
    out = img.convertToFormat(QImage.Format_RGB32)
    if abs(lift - 1.0) < 0.01 and abs(saturate - 1.0) < 0.01:
        return out
    lut = [min(255, int(((i / 255.0) ** lift) * 255 + 0.5)) for i in range(256)]
    buf = out.bits()
    size = out.sizeInBytes()
    for i in range(0, size, 4):
        # Format_RGB32 在小端机上的字节序是 B, G, R, A
        b = lut[buf[i]]
        g = lut[buf[i + 1]]
        r = lut[buf[i + 2]]
        gray = (r * 299 + g * 587 + b * 114) // 1000
        b = int(gray + (b - gray) * saturate)
        g = int(gray + (g - gray) * saturate)
        r = int(gray + (r - gray) * saturate)
        buf[i] = 0 if b < 0 else (255 if b > 255 else b)
        buf[i + 1] = 0 if g < 0 else (255 if g > 255 else g)
        buf[i + 2] = 0 if r < 0 else (255 if r > 255 else r)
    return out


def _pad_edge(img: QImage, pad: int) -> QImage:
    """把边缘像素向外复制一圈。

    高斯在图像边界会被"透明"污染，边缘发暗；复制边缘像素等于把画面往外延伸，
    模糊后才不会在卡片四周出现一圈灰边。
    """
    w, h = img.width(), img.height()
    out = QImage(w + pad * 2, h + pad * 2, QImage.Format_RGB32)
    out.fill(QColor(0, 0, 0))
    p = QPainter(out)
    p.drawImage(pad, pad, img)
    for i in range(pad):
        p.drawImage(pad, i, img, 0, 0, w, 1)
        p.drawImage(pad, pad + h + i, img, 0, h - 1, w, 1)
    p.end()
    p = QPainter(out)
    for i in range(pad):
        p.drawImage(i, 0, out, pad, 0, 1, out.height())
        p.drawImage(pad + w + i, 0, out, pad + w - 1, 0, 1, out.height())
    p.end()
    return out


def _blur(img: QImage, radius: float) -> QImage:
    """真高斯模糊（Qt 自带实现，纯软件，不碰 OpenGL）。"""
    if radius <= 0.2:
        return img
    pad = int(radius * 2) + 4
    big = _pad_edge(img, pad)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(big))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QImage(big.size(), QImage.Format_RGB32)
    out.fill(QColor(0, 0, 0))
    p = QPainter(out)
    scene.render(p, QRectF(out.rect()), QRectF(big.rect()))
    p.end()
    return out.copy(pad, pad, img.width(), img.height())


def _mean_light(img: QImage) -> float:
    """底图平均亮度（先缩到 32×18 再采样，几千次像素读取也不到 1ms）。"""
    tiny = img.scaled(32, 18, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    total = 0
    n = 0
    for y in range(tiny.height()):
        for x in range(tiny.width()):
            c = tiny.pixelColor(x, y)
            total += (c.red() * 299 + c.green() * 587 + c.blue() * 114) // 1000
            n += 1
    return total / max(1, n)


class ScreenBlur:
    """一张屏幕的模糊副本 + 坐标换算。"""

    def __init__(self) -> None:
        self.image: QImage | None = None
        self.origin = QPoint(0, 0)
        self.scale = 1.0          # 模糊图像素 / 逻辑像素
        self.brightness = 128.0   # 底图平均亮度 0–255，用来决定染色厚薄

    def release(self) -> None:
        self.image = None

    def capture(self, screen: QScreen | None, region: QRect | None = None,
                downscale: int | None = None, blur: float | None = None,
                margin: int = 32) -> bool:
        self.release()
        if screen is None or QApplication.instance() is None:
            return False
        try:
            geo: QRect = screen.geometry()
            # 只抓卡片背后那一小块。整屏位图在 2K 上就要二十多兆，
            # 卡片本身不到四百像素宽，用不到那张全屏。
            if region is not None and not region.isNull():
                grab = region.adjusted(-margin, -margin, margin, margin).intersected(geo)
            else:
                grab = geo
            if grab.isEmpty():
                return False
            pm = screen.grabWindow(
                0, grab.x() - geo.x(), grab.y() - geo.y(),
                grab.width(), grab.height(),
            )
            if pm.isNull() or grab.width() <= 0 or grab.height() <= 0:
                return False
            img = pm.toImage().convertToFormat(QImage.Format_RGB32)
            del pm
            if img.isNull():
                return False
            downscale = DOWNSCALE if downscale is None else downscale
            blur = BLUR_PX if blur is None else blur
            small = img.scaled(max(16, img.width() // downscale),
                               max(16, img.height() // downscale),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            del img
            self.image = _blur(_grade(small), blur)
            self.origin = grab.topLeft()
            self.scale = self.image.width() / float(grab.width())
            self.brightness = _mean_light(self.image)
            return True
        except Exception:
            self.image = None
            return False

    @property
    def ready(self) -> bool:
        return self.image is not None and not self.image.isNull()

    def paint(self, p: QPainter, target: QRectF, screen_rect: QRect) -> bool:
        """把 screen_rect 这块区域的模糊影像铺到 target 上。"""
        if not self.ready or self.image is None:
            return False
        s = self.scale
        src = QRectF(
            (screen_rect.x() - self.origin.x()) * s,
            (screen_rect.y() - self.origin.y()) * s,
            max(1.0, screen_rect.width() * s),
            max(1.0, screen_rect.height() * s),
        )
        bounds = QRectF(0.0, 0.0, float(self.image.width()), float(self.image.height()))
        if not bounds.contains(src):
            clamped = src.intersected(bounds)
            if clamped.width() < src.width() * 0.9 or clamped.height() < src.height() * 0.9:
                return False
            src = clamped
        if src.width() <= 0.5 or src.height() <= 0.5:
            return False
        p.drawImage(target, self.image, src)
        return True
