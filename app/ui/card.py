# -*- coding: utf-8 -*-
"""点击托盘后向上展开的电量卡片。

结构：一张卡片，两页切换 —— 设备列表页 / 设置页。
不带任何说明性文案，信息只留设备名与电量。
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRect, Qt, Signal,
)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

import theme
from config import INTERVALS, Config
from model import Device
from ui.glass import ScreenBlur
from ui.glasscard import GlassCard
from ui.widgets import DeviceRow, IconButton, ToggleSwitch

CARD_WIDTH = 344
CARD_PAD = 18
# 窗口给投影留的边距。苹果那种浮起来的玻璃，靠的是一大片很淡的投影；
# 留白太小投影会被裁掉，只剩一圈硬边，材质感就没了。
SHADOW_PAD = 22
SHADOW_BLUR = 46
SHADOW_GAP = 20     # 卡片可见底边离托盘图标的距离（原来的 14 留白 + 6 空隙）


class CardWindow(QWidget):
    refresh_requested = Signal()
    interval_changed = Signal(int)
    autostart_changed = Signal(bool)
    theme_changed = Signal(str)
    diag_requested = Signal()

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self._rows: dict[str, DeviceRow] = {}
        self._devices: list[Device] = []
        self._settings_open = False
        self._hide_anim: QParallelAnimationGroup | None = None
        self._pos_anim: QPropertyAnimation | None = None
        self._suppress_hide = False
        self._syncing = False
        self.interval_note: QLabel | None = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("外设电量")
        self.setStyleSheet(theme.qss())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_PAD, SHADOW_PAD, SHADOW_PAD, SHADOW_PAD)
        outer.setSpacing(0)

        self.card = GlassCard()
        self.card.setFixedWidth(CARD_WIDTH)
        self._blur = ScreenBlur()
        self.card.set_enabled(bool(self.config.get("glass")))
        self._shadow = QGraphicsDropShadowEffect(self.card)
        self._shadow.setBlurRadius(SHADOW_BLUR)
        self._shadow.setOffset(0, 7)
        self.card.setGraphicsEffect(self._shadow)
        self._apply_shadow_color()
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(CARD_PAD, 10, CARD_PAD, 13)
        lay.setSpacing(4)
        lay.addLayout(self._build_header())

        self.list_page = self._build_list()
        lay.addWidget(self.list_page)

        self.settings_page = self._build_settings()
        self.settings_page.setVisible(False)
        lay.addWidget(self.settings_page)

        self.adjustSize()

    # ---------------- 头部 ----------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(2)
        row.setContentsMargins(0, 0, 0, 0)

        # 列表页不再显示"键盘/鼠标"这类类型标题：一台设备时它就是废话，
        # 多台时也没人靠它认设备。标题只留给设置页做页面名。
        self.header_label = QLabel("")
        self.header_label.setObjectName("HeaderLabel")
        row.addWidget(self.header_label, 0, Qt.AlignVCenter)
        row.addStretch(1)

        self.refresh_btn = IconButton("refresh", size=24, icon_size=13)
        self.refresh_btn.setToolTip("立即刷新")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self.refresh_btn, 0, Qt.AlignVCenter)

        self.gear_btn = IconButton("gear", size=24, icon_size=14)
        self.gear_btn.setToolTip("设置")
        self.gear_btn.clicked.connect(self.toggle_settings)
        row.addWidget(self.gear_btn, 0, Qt.AlignVCenter)
        return row

    # ---------------- 列表页 ----------------
    def _build_list(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.devices_box = QVBoxLayout()
        self.devices_box.setSpacing(0)
        self.devices_box.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.devices_box)

        self.empty_label = QLabel("正在读取…")
        self.empty_label.setObjectName("Empty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(44)
        lay.addWidget(self.empty_label)
        return page

    # ---------------- 设置页 ----------------
    def _build_settings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(12)

        self._chips: dict[int, QPushButton] = {}
        block, self.interval_note = self._chip_block(
            "刷新间隔 · 分钟", [(m, str(m)) for m in INTERVALS],
            self._pick_interval, self._chips,
            note="（上次刷新 —）",
        )
        lay.addLayout(block)

        self._theme_chips: dict[str, QPushButton] = {}
        self._theme_group = QButtonGroup(page)
        self._theme_group.setExclusive(True)
        block, _ = self._chip_block(
            "外观", [(m, theme.MODE_LABEL[m]) for m in theme.MODES],
            self._pick_theme, self._theme_chips, group=self._theme_group,
        )
        lay.addLayout(block)
        self._sync_theme_chips()

        self.glass_switch = self._switch_row(
            lay, "毛玻璃", bool(self.config.get("glass")), self._on_glass,
        )

        self.autostart_switch = self._switch_row(
            lay, "开机自启动", bool(self.config.get("autostart")),
            self._on_autostart,
        )

        self.diag_btn = QPushButton("设备诊断")
        self.diag_btn.setObjectName("Ghost")
        self.diag_btn.setFixedHeight(22)
        self.diag_btn.setCursor(Qt.PointingHandCursor)
        self.diag_btn.clicked.connect(self.diag_requested.emit)
        lay.addWidget(self.diag_btn)

        self._sync_chips()
        return page

    def _chip_block(self, label_text: str, options, handler, store: dict,
                    note: str | None = None, group: QButtonGroup | None = None):
        """标题 + （可选的小字备注）+ 选项行。返回 (布局, 备注标签)。"""
        block = QVBoxLayout()
        block.setSpacing(7)
        block.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        head.setSpacing(5)
        head.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setObjectName("SectionLabel")
        head.addWidget(label, 0, Qt.AlignVCenter)
        note_label = None
        if note is not None:
            note_label = QLabel(note)
            note_label.setObjectName("SectionNote")
            head.addWidget(note_label, 0, Qt.AlignVCenter)
        head.addStretch(1)
        block.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        for value, text in options:
            btn = QPushButton(text)
            btn.setObjectName("Chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, v=value: handler(v))
            if group is not None:
                group.addButton(btn)
            row.addWidget(btn)
            store[value] = btn
        block.addLayout(row)
        return block, note_label

    def _switch_row(self, parent_lay, title: str, checked: bool, handler):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 1, 0, 0)
        t = QLabel(title)
        t.setObjectName("SwitchLabel")
        row.addWidget(t, 1, Qt.AlignVCenter)
        switch = ToggleSwitch(checked)
        switch.toggled.connect(handler)
        row.addWidget(switch, 0, Qt.AlignVCenter)
        parent_lay.addLayout(row)
        return switch

    # ---------------- 交互 ----------------
    def _pick_interval(self, minutes: int) -> None:
        self.config.interval_minutes = minutes
        self._sync_chips()
        self.interval_changed.emit(minutes)

    def _sync_chips(self) -> None:
        current = self.config.interval_minutes
        for minutes, btn in self._chips.items():
            btn.setChecked(minutes == current)

    def _pick_theme(self, mode: str) -> None:
        # 外观必须始终有一个选中项。再点当前项时 Qt 会先把按钮取消，
        # 这里立刻选回去，不能留成深色、浅色都空着。
        self._sync_theme_chips()
        if mode == theme.current_mode():
            return
        self.config.set("theme", mode)
        self._sync_theme_chips()
        self.theme_changed.emit(mode)

    def _sync_theme_chips(self) -> None:
        current = theme.current_mode()
        for mode, btn in self._theme_chips.items():
            btn.setChecked(mode == current)

    def _on_autostart(self, checked: bool) -> None:
        if self._syncing:
            return
        self.config.set("autostart", checked)
        self.autostart_changed.emit(checked)

    def _on_glass(self, checked: bool) -> None:
        if self._syncing:
            return
        self.config.set("glass", bool(checked))
        self.card.set_enabled(bool(checked))
        if checked:
            self._capture_glass()
        else:
            self.card.attach(None)
            self._blur.release()

    def _capture_glass(self) -> None:
        """抓屏做毛玻璃底图。

        抓屏时卡片必须真的不在屏幕上：只把 windowOpacity 设成 0 是不够的，
        Windows 对这种分层窗口的透明度变化有过渡，几十毫秒内它还在屏幕上，
        抓到的是卡片自己 —— 底图在卡片位置是一块白，玻璃就永远是一块白板。
        所以这里先 hide() 再抓，抓完立刻 show() 回来，并屏蔽这一次的失焦收起。
        """
        if not bool(self.config.get("glass")):
            self.card.attach(None)
            return
        center = QPoint(self.x() + self.width() // 2, self.y() + self.height() // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        # 无边框窗口的坐标就是卡片外沿。毛玻璃只取中间那一块，不抓整屏。
        region = QRect(self.pos() + QPoint(SHADOW_PAD, SHADOW_PAD), self.card.size())
        visible = self.isVisible()
        if visible:
            import time

            self._suppress_hide = True
            self.hide()
            QGuiApplication.processEvents()
            time.sleep(0.035)
            QGuiApplication.processEvents()
        # 浅色霜化薄，背后窗口的矩形边会透出来。多抓一圈、把模糊加大，边才化开。
        light = theme.current_mode() == "light"
        ok = self._blur.capture(
            screen, region,
            downscale=4 if light else None,
            blur=11.0 if light else None,
            margin=80 if light else 32,
        )
        self.card.attach(self._blur if ok else None)
        if visible:
            self.show()
            self.raise_()
            self.activateWindow()
            self._suppress_hide = False
            self.update()

    def toggle_settings(self) -> None:
        self._settings_open = not self._settings_open
        self.list_page.setVisible(not self._settings_open)
        self.settings_page.setVisible(self._settings_open)
        self.refresh_btn.setVisible(not self._settings_open)
        self.gear_btn.shape = "close" if self._settings_open else "gear"
        self.gear_btn.icon_size = 12 if self._settings_open else 14
        self.gear_btn.setToolTip("返回" if self._settings_open else "设置")
        self.gear_btn.update()
        self.header_label.setText("设置" if self._settings_open else "")
        self._relayout()
        self._reposition()

    def _relayout(self) -> None:
        """内容变化后重新计算窗口尺寸（含页面切换）。

        嵌套页面（列表页/设置页）需要逐层 activate，否则卡片只按
        空页面的最小高度收缩。
        """
        for page in (self.list_page, self.settings_page):
            page_layout = page.layout()
            if page_layout is not None:
                page_layout.activate()
            page.updateGeometry()
        card_layout = self.card.layout()
        if card_layout is not None:
            card_layout.activate()
        self.card.updateGeometry()
        outer = self.layout()
        if outer is not None:
            outer.activate()
        self.adjustSize()

    # ---------------- 主题 ----------------
    def _apply_shadow_color(self) -> None:
        self._shadow.setColor(QColor(0, 0, 0, theme.SHADOW_ALPHA))

    def apply_theme(self) -> None:
        """全局换肤后刷新自身与所有子控件。"""
        self.setStyleSheet(theme.qss())
        self._apply_shadow_color()
        self._sync_theme_chips()
        for row in self._rows.values():
            row.apply(row.device, animate=False)
        self.card.update()
        self.update()
        self._relayout()
        if self.isVisible():
            self._reposition()

    # ---------------- 数据刷新 ----------------
    def set_devices(self, devices: list[Device], error: str | None = None,
                    animate: bool = True) -> None:
        self._devices = list(devices)
        keys = [d.key for d in devices]

        for key in list(self._rows.keys()):
            if key not in keys:
                row = self._rows.pop(key)
                row.setParent(None)
                row.deleteLater()

        for index, device in enumerate(devices):
            row = self._rows.get(device.key)
            if row is None:
                row = DeviceRow(device, animate=animate)
                self._rows[device.key] = row
                self.devices_box.insertWidget(index, row)
            else:
                row.apply(device, animate=animate)
        # 保证顺序
        for index, device in enumerate(devices):
            row = self._rows.get(device.key)
            if row is not None and self.devices_box.indexOf(row) != index:
                self.devices_box.removeWidget(row)
                self.devices_box.insertWidget(index, row)

        self.empty_label.setVisible(not devices)
        if not devices:
            self.empty_label.setText(error or "未检测到无线外设")

        self._relayout()
        if self.isVisible():
            self._reposition()

    def set_last_refresh(self, hhmm: str) -> None:
        """标题旁小字：上次刷新时间（HH:mm）。"""
        if getattr(self, "interval_note", None) is not None:
            self.interval_note.setText(
                f"（上次刷新 {hhmm}）" if hhmm else "（上次刷新 —）"
            )

    def set_loading(self, loading: bool) -> None:
        if loading and not self._rows:
            self.empty_label.setText("正在读取…")
            self.empty_label.setVisible(True)
        if loading:
            self.refresh_btn.start_spin()
        else:
            # 只有正在转（手动刷新）才播"完成对勾"，自动刷新静默收尾
            self.refresh_btn.finish()

    def sync_from_config(self) -> None:
        """外部（菜单/注册表）改动后同步控件，不触发回写。"""
        self._syncing = True
        try:
            self._sync_chips()
            self._sync_theme_chips()
            glass = bool(self.config.get("glass"))
            self.card.set_enabled(glass)
            sw_glass = self.glass_switch
            sw_glass.blockSignals(True)
            sw_glass.setChecked(glass)
            sw_glass.set_knob(1.0 if glass else 0.0)
            sw_glass.blockSignals(False)

            value = bool(self.config.get("autostart"))
            switch = self.autostart_switch
            switch.blockSignals(True)
            switch.setChecked(value)
            switch.set_knob(1.0 if value else 0.0)
            switch.blockSignals(False)
        finally:
            self._syncing = False

    # ---------------- 窗口行为 ----------------
    def show_near(self, tray_rect: QRect) -> None:
        screen = QGuiApplication.screenAt(tray_rect.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self._relayout()
        self.resize(self.sizeHint())

        # 以托盘图标为锚点：底边贴着图标上方，内容变高时向上生长
        self._anchor_x = tray_rect.center().x()
        # 锚点算的是窗口底边，而可见卡片的底边还要往里收一个 SHADOW_PAD，
        # 这里补偿掉，保证卡片与图标的视觉间距不随投影留白变化
        self._anchor_bottom = min(
            tray_rect.top() - SHADOW_GAP + SHADOW_PAD, geo.bottom() - 4
        )

        w, h = self.width(), self.height()
        x = self._clamp_x(self._anchor_x - w // 2, w, geo)
        y = max(geo.top() + 8, self._anchor_bottom - h)

        self.setWindowOpacity(0.0)
        self.move(x, y + 10)

        # 抓一张屏幕当毛玻璃底图：此刻卡片还没显示，抓到的正是它背后的画面
        self._capture_glass()

        self.show()
        self.raise_()
        self.activateWindow()

        anim_pos = QPropertyAnimation(self, b"pos", self)
        anim_pos.setDuration(160)
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)
        anim_pos.setStartValue(QPoint(x, y + 10))
        anim_pos.setEndValue(QPoint(x, y))
        self._pos_anim = anim_pos

        anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        anim_op.setDuration(140)
        anim_op.setStartValue(0.0)
        anim_op.setEndValue(1.0)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_pos)
        group.addAnimation(anim_op)
        group.finished.connect(self._settle_after_show)
        group.start()

    def _settle_after_show(self) -> None:
        """入场动画结束后再对一次位：万一首帧布局把高度撑大了，这里收回来。"""
        if self.isVisible():
            self._reposition()

    @staticmethod
    def _clamp_x(x: int, w: int, geo) -> int:
        return max(geo.left() + 8, min(x, geo.right() - w - 8))

    def _reposition(self) -> None:
        anchor_bottom = getattr(self, "_anchor_bottom", None)
        if anchor_bottom is None:
            return
        # 入场位移动画记的是"展开那一刻的高度"算出的坐标。页面变高（比如刚切到
        # 设置页）时它还在播，就会一帧一帧把窗口拉回下面的旧位置——表现为
        # "第一次打开设置，弹窗往下掉"。内容一变就让动画先退场，落位以新高度为准。
        anim = getattr(self, "_pos_anim", None)
        if anim is not None and anim.state() == QAbstractAnimation.Running:
            anim.stop()
        screen = (QGuiApplication.screenAt(QPoint(self._anchor_x, anchor_bottom))
                  or QGuiApplication.primaryScreen())
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = self._clamp_x(self._anchor_x - w // 2, w, geo)
        y = max(geo.top() + 8, anchor_bottom - h)
        self.move(x, y)

    def hide_card(self) -> None:
        if not self.isVisible():
            return
        import time

        self._hide_stamp = time.monotonic()
        anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        anim_op.setDuration(100)
        anim_op.setStartValue(self.windowOpacity())
        anim_op.setEndValue(0.0)
        anim_op.finished.connect(self._finish_hide)
        self._hide_anim = QParallelAnimationGroup(self)
        self._hide_anim.addAnimation(anim_op)
        self._hide_anim.start()

    def _finish_hide(self) -> None:
        self.hide()
        self.card.attach(None)
        self._blur.release()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self._settings_open:
                self.toggle_settings()
            else:
                self.hide_card()
            return
        super().keyPressEvent(event)

    def event(self, ev) -> bool:
        if (ev.type() == QEvent.WindowDeactivate and self.isVisible()
                and not self._suppress_hide):
            self.hide_card()
        return super().event(ev)
