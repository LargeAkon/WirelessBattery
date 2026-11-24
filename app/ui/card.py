# -*- coding: utf-8 -*-
"""点击托盘后向上展开的电量卡片。

结构：一张卡片，两页切换 —— 设备列表页 / 设置页。
不带任何说明性文案，信息只留设备名与电量。
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

import theme
from config import INTERVALS, Config
from model import Device
from ui.glass import ScreenBlur
from ui.glasscard import GlassCard
from ui.reveal import RevealOverlay
from ui.widgets import DeviceRow, IconButton, ToggleSwitch

CARD_WIDTH = 344
CARD_PAD = 18
# 不再给投影留边：卡片四周那一圈黑影既不好看也不必要 —— 46px 的模糊
# 塞在 22px 的窗口留白里，投影在半路被窗口边界裁断，四个角就成了硬邦邦
# 的黑三角。现在窗口边界 == 卡片边界，轮廓交给卡片自己的 1px 描边。
# 顺带的好处：grab 一张没有效果滤镜的窗口只要 1ms 左右（以前要跑 46px
# 高斯），换肤动效起手更快。
SHADOW_PAD = 0
SHADOW_GAP = 20     # 卡片底边离托盘图标的距离
# 毛玻璃底图的余量。卡片底边钉在托盘上方，切到设置页时整张卡片向上长
# 170 多像素、顶边跑到旧底图之外；底图盖不满卡片时 ScreenBlur.paint 会
# 直接返回 False，材质静默退回实底 —— 就是"刚装好第一次点毛玻璃没反应，
# 关掉重开才正常"。所以上方多留 240px，左右与下方各 90px 够模糊化边。
BACKDROP_TOP = 240
BACKDROP_SIDE = 90
# 浅色霜化薄，背后窗口的矩形边会透出来，模糊要下得更重才化得开。
# 深色材质本身就压得住，用 glass.py 里的默认值即可。
LIGHT_DOWNSCALE = 4
LIGHT_BLUR = 20.0


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
        # 悬停弹出（activate=False）的卡片不抢焦点；用户点开的那张才算"锁定"，
        # 鼠标移走不会自己收起。
        self._hover_shown = False
        # 换肤动效的盖板（独立顶层窗口）：换肤前先盖一张旧皮肤，
        # 新皮肤在盖板底下画完再圆形揭开 —— 全程屏幕上不会出现"裸的新皮肤"。
        self._reveal: RevealOverlay | None = None
        self._hide_stamp = 0.0
        # 失焦收起不再"收到就藏"：Qt 的 WindowDeactivate 会掺进假信号
        # （盖板出现/消失、换肤时整窗重刷都可能触发一次），这里用序号把
        # 多次失活折叠成一次延后确认，确认不下来就当没发生。
        self._deactivate_gen = 0

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
        # 换肤动效分两步走，这里是第一步：趁皮肤还没换，截下旧图、
        # 从点中的选项处盖一层"旧皮肤"浮层 —— 之后随便怎么重绘都闪不了。
        btn = self._theme_chips.get(mode)
        if btn is not None:
            self._start_reveal(self._reveal_origin(btn))
        self._sync_theme_chips()
        self.theme_changed.emit(mode)
        # 写盘放最后，再错开 260ms：JSON + 落盘本身只要 ~1ms，但它落在
        # "点击 → 第一帧"这段最敏感的路径上就可能是掉一帧的元凶。等动效
        # 跑起来再写，用户完全感知不到。
        QTimer.singleShot(260, lambda: self.config.set("theme", mode))

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
        # 和换肤同一套动效：先从开关处盖一层旧材质，换完再圆形揭开。
        # 底图是显示卡片之前就抓好的，这里只是换一张材质 ——
        # 不藏窗口、不等待、不阻塞主线程，所以不闪也不卡。
        self._start_reveal(self._reveal_origin(self.glass_switch))
        # 旧图已经截好（里面还是没拨的样子），这里立刻把 knob 拨到位。
        # 揭开的圆是从开关长出去的，新图里必须已经是"拨过去"的状态；
        # 若还走 180ms 滑动动画，得等揭开（780ms）结束它才动完，
        # 观感就是"点了没反应，非要等毛玻璃生效才切换"。
        self.glass_switch.snap(bool(checked))
        self.card.set_enabled(bool(checked))
        if checked:
            self._attach_glass()
        else:
            # 只摘掉不释放：再打开时还要用同一张底图
            self.card.attach(None)
        self._sync_overlay()
        self._finish_reveal()
        QTimer.singleShot(260, lambda: self.config.set("glass", bool(checked)))

    def _grab_backdrop(self) -> bool:
        """抓屏做毛玻璃底图。

        只允许在卡片没显示时调用 —— 卡片遮住的那块，抓出来是卡片自己。
        `show_near` 在 show() 之前调它：那一刻窗口还不在屏幕上，抓到的正是
        背景，既不用把窗口藏起来、也不用 sleep 等它消失（那一次的"消失再
        出现"就是以前点毛玻璃开关会闪一下、按钮还卡半秒的来源）。

        不论毛玻璃开关开着还是关着都抓一张（一次 5~15ms）：用户随后点开关
        时可以立刻换材质，不必再抓。

        抓取范围必须比卡片本身大一圈，而且这一圈得容得下"页面变高"：
        卡片底边钉在托盘上方，切到设置页时整张卡片向上长 170 多像素，
        顶边会跑到原来的底图之外。底图盖不满卡片，`ScreenBlur.paint` 会
        直接返回 False，卡片退回实底 —— 表现就是"刚装好第一次点毛玻璃
        没反应，关掉重开才正常"（重开时按新高度重新抓了一张）。
        所以上方按 BACKDROP_TOP 加大余量，比任何一次页面切换的增高都多。
        """
        if self.isVisible():
            return False
        center = QPoint(self.x() + self.width() // 2, self.y() + self.height() // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        # 无边框窗口的坐标就是卡片外沿。毛玻璃只取中间那一块，不抓整屏。
        base = QRect(self.pos() + QPoint(SHADOW_PAD, SHADOW_PAD), self.card.size())
        region = base.adjusted(-BACKDROP_SIDE, -BACKDROP_TOP,
                               BACKDROP_SIDE, BACKDROP_SIDE)
        # 浅色霜化薄，背后窗口的矩形边会透出来。模糊加大，边才化开。
        light = theme.current_mode() == "light"
        ok = self._blur.capture(
            screen, region,
            downscale=LIGHT_DOWNSCALE if light else None,
            blur=LIGHT_BLUR if light else None,
            margin=24,
        )
        if not ok:
            self._blur.release()
        return ok

    def _attach_glass(self) -> None:
        """把已抓好的底图挂上去。没有底图就朴素配色，绝不再去藏窗口重抓。"""
        self.card.attach(self._blur if self._blur.ready else None)

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
    def apply_theme(self, origin: QPoint | None = None) -> None:
        """全局换肤后刷新自身与所有子控件。

        动效盖板由 _pick_theme 提前盖好（origin 参数仅为兼容旧调用，
        现在圆心取自盖板创建时点中的那个选项框）。窗口没显示、或截不到
        图时静静走普通切换，不播动效。
        """
        self.setStyleSheet(theme.qss())
        self._sync_theme_chips()
        for row in self._rows.values():
            row.apply(row.device, animate=False)
        self.card.update()
        self.update()
        # 只换颜色，尺寸本来不该变。真变了（字体回退之类）才重排重落位；
        # 否则跳过这两步 —— 多一次 resize/move 就是肉眼可见的"抖一下"。
        if self.sizeHint() != self.size():
            self._relayout()
            if self.isVisible():
                self._reposition()
        self._sync_overlay()
        self._finish_reveal()

    # ---------------- 换肤动效 ----------------
    def _card_global_rect(self) -> QRect:
        """卡片本体在屏幕上的矩形。窗口就是卡片本体，两者一致。"""
        return QRect(self.card.mapToGlobal(QPoint(0, 0)), self.card.size())

    def _card_snapshot(self):
        """截一张卡片本体。

        卡片四周的投影已经去掉（窗口边界 == 卡片边界），整窗截图就是卡片
        本体；SHADOW_PAD 仍保留在代码里，是为了万一以后再给投影留边时，
        这里还能按留白裁掉 —— 半透明投影贴进盖板会和新皮肤再叠一层，
        圆内更黑、收尾忽然变淡，看着像抖一下。
        """
        if not self.isVisible():
            return None
        pm = self.grab()
        if pm is None or pm.isNull():
            return None
        if SHADOW_PAD <= 0:
            # 窗口就是卡片本体，整张图都是要的，不用再裁一刀
            return pm
        dpr = pm.devicePixelRatio() or 1.0
        rect = QRect(round(SHADOW_PAD * dpr), round(SHADOW_PAD * dpr),
                     round(self.card.width() * dpr), round(self.card.height() * dpr))
        out = pm.copy(rect)
        out.setDevicePixelRatio(dpr)
        return out

    def _start_reveal(self, origin: QPoint | None) -> RevealOverlay | None:
        """第一步：趁皮肤还没换，截旧图、盖盖板。

        盖板贴的就是旧皮肤，所以从它出现到揭开之间，屏幕上始终是旧皮肤
        或"旧皮肤被圆一点一点换成新皮肤"，不会闪出一张裸的新皮肤。
        """
        self._drop_reveal()
        if origin is None or not self.isVisible():
            return None
        before = self._card_snapshot()
        if before is None or before.isNull():
            return None
        overlay = RevealOverlay(self, before, origin, self._card_global_rect(),
                                on_closed=self._on_reveal_closed)
        if not overlay.active:
            return None
        self._reveal = overlay
        # 让盖板真正映射到屏幕上再动皮肤：此刻还没换肤，怎么画都不会闪
        QGuiApplication.processEvents()
        return overlay

    def _on_reveal_closed(self, overlay) -> None:
        # 盖板播完自毁后第一时间松手，别攥着一个已删除的 C++ 包装
        if self._reveal is overlay:
            self._reveal = None

    def _finish_reveal(self) -> None:
        """第二步：皮肤已换完。截新图（盖板是独立窗口，不会被截进去），
        开始圆形揭开。"""
        overlay = self._reveal
        if overlay is None or not overlay.active:
            self._drop_reveal()
            return
        if not self.isVisible():
            self._drop_reveal()
            return
        # 新皮肤在盖板底下先画完，grab 才截得到它；盖板盖着，用户看不见
        QGuiApplication.processEvents()
        overlay.set_new_and_start(self._card_snapshot())

    def _drop_reveal(self) -> None:
        overlay = self._reveal
        self._reveal = None
        if overlay is not None and overlay.active:
            overlay.close_reveal()

    def _sync_overlay(self) -> None:
        overlay = self._reveal
        if overlay is not None and overlay.active:
            if not overlay.isVisible():
                overlay.show()
                overlay.raise_()
            overlay.sync_geometry(self._card_global_rect())

    def _reveal_origin(self, widget: QWidget) -> QPoint | None:
        """控件中心映射到**卡片本体**坐标，并夹进卡片范围（盖板只盖卡片）。

        设置页在列表页显示时是隐藏的，隐藏页里的控件几何可能还是
        "未布局"的旧值；圆心跑到卡片外，圆就会从卡片外面长进来。
        """
        point = widget.mapTo(self.card, widget.rect().center())
        w = max(1, self.card.width())
        h = max(1, self.card.height())
        if not (0 <= point.x() <= w and 0 <= point.y() <= h):
            return None
        point.setX(max(6, min(point.x(), w - 6)))
        point.setY(max(6, min(point.y(), h - 6)))
        return point

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
            # 空列表是用户放弃率最高的地方：这里给一句"下一步点哪里"，
            # 比只写"未检测到"有用得多。
            self.empty_label.setText(
                error or "未检测到无线外设\n右键托盘图标 → 设备诊断，可自动查找")

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
            if glass:
                self._attach_glass()
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
    def show_near(self, tray_rect: QRect, activate: bool = True) -> None:
        """显示卡片。activate=False 用于悬停弹出：只出现，不抢当前窗口的焦点。"""
        screen = QGuiApplication.screenAt(tray_rect.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self._relayout()
        self.resize(self.sizeHint())

        # 以托盘图标为锚点：底边贴着图标上方，内容变高时向上生长
        self._anchor_x = tray_rect.center().x()
        # 锚点是窗口底边；窗口边界 == 卡片边界，直接留出 SHADOW_GAP 即可
        self._anchor_bottom = min(
            tray_rect.top() - SHADOW_GAP + SHADOW_PAD, geo.bottom() - 4
        )

        w, h = self.width(), self.height()
        x = self._clamp_x(self._anchor_x - w // 2, w, geo)
        y = max(geo.top() + 8, self._anchor_bottom - h)

        self.setWindowOpacity(0.0)
        self.move(x, y + 10)

        # 抓一张屏幕当毛玻璃底图：此刻卡片还没显示，抓到的正是它背后的画面。
        # 开不开毛玻璃都抓，点开关时才有现成的材质可换。
        self._grab_backdrop()
        if bool(self.config.get("glass")):
            self._attach_glass()

        self.show()
        self.raise_()
        # 悬停弹出时把焦点留在用户原来的窗口：正在打字的人不该被一个
        # 冒出来的卡片打断
        self._hover_shown = not activate
        if activate:
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

    def moveEvent(self, ev) -> None:  # noqa: N802
        # 盖板是独立窗口，卡片挪窝它不会跟着走，得手动拽一把
        self._sync_overlay()
        super().moveEvent(ev)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        self._sync_overlay()
        super().resizeEvent(ev)

    def hide_card(self) -> None:
        if not self.isVisible():
            return
        import time

        self._hide_stamp = time.monotonic()
        # 卡片要没了，盖板没有继续存在的意义
        self._drop_reveal()
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
        self._hover_shown = False
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
        if (ev.type() == QEvent.WindowActivate and self.isVisible()
                and self._hover_shown):
            # 用户在卡片里点了东西：这张卡片从此是"点开的"，不再跟着鼠标走
            self._hover_shown = False
        if (ev.type() == QEvent.WindowDeactivate and self.isVisible()
                and not self._suppress_hide):
            # 见 _confirm_deactivate：失活先记账，140ms 后再核实是不是真失焦
            self._deactivate_gen += 1
            gen = self._deactivate_gen
            QTimer.singleShot(140, lambda: self._confirm_deactivate(gen, 0))
        return super().event(ev)

    # ---------------- 失焦收起 ----------------
    def _confirm_deactivate(self, gen: int, tries: int) -> None:
        """确认"真的失焦了"再收起。

        为什么不能收到 WindowDeactivate 就藏：换肤动效的盖板是另一个顶层
        窗口，盖板出现、销毁，以及换肤时的整窗重刷，都会让 Windows 给卡片
        补一个 WA_INACTIVE（Qt 就翻译成 WindowDeactivate），可前台窗口其实
        一直是卡片自己。此时若照旧 hide_card，表现就是"点一下颜色，卡片
        瞬间消失"——点了毛玻璃之后特别容易撞上，因为那次点击一定会先立一块
        盖板。

        所以这里做三件事：
        1. 延后 140ms 再判断，把同一轮的连串假失活折叠掉；
        2. 用原生前台窗口核对 —— 前台还是卡片（或盖板）就说明是假信号，
           不动；盖板还在播动效时也先不动（把卡片藏了，盖板上那张旧图
           会孤零零悬在空中），隔一会儿再问；
        3. 光标还压在卡片上就说明没人去点别处，同样按噪声丢掉 ——
           点完颜色/开关那一瞬间，鼠标必定还在卡片里。
        """
        if gen != self._deactivate_gen or not self.isVisible():
            return                     # 已有更新的一轮判断，交给它
        if self._suppress_hide:
            return
        overlay = self._reveal
        if overlay is not None and overlay.active and tries < 16:
            # 盖板还在（最多 780ms 动效 + 收尾），等它播完再核实，
            # 否则卡片可能在"圆还没揭开"时就没了
            if not overlay.isVisible():
                overlay.show()
                overlay.raise_()
            QTimer.singleShot(120, lambda: self._confirm_deactivate(gen, tries + 1))
            return
        if self._foreground_is_ours():
            return
        if self._cursor_over_card():
            # 鼠标还在卡片里，人就不可能"去点了别的窗口"——这次的失活
            # 是我们自己刚做的动效/换肤刷出来的噪声，丢掉。
            return
        if QApplication.activeModalWidget() is not None:
            return
        if QApplication.activePopupWidget() is not None:
            return
        self.hide_card()

    def _cursor_over_card(self) -> bool:
        """光标是否还压在卡片上（含 4px 容差）。"""
        try:
            from PySide6.QtGui import QCursor

            return self.frameGeometry().adjusted(-4, -4, 4, 4).contains(QCursor.pos())
        except Exception:
            return False

    def _foreground_is_ours(self) -> bool:
        """原生前台窗口是不是本卡片（或换肤盖板）。

        Qt 的 isActiveWindow()/activeWindow() 在有盖板这类
        NOACTIVATE 顶层窗口时并不可靠（实测会把 activeWindow 记成 None），
        所以直接问一次系统。
        """
        try:
            import ctypes

            fg = int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:
            return False
        if not fg:
            return False                 # 查不到就别当"还是自己"，交给下面按失焦处理
        try:
            if fg == int(self.winId()):
                return True
        except Exception:
            pass
        overlay = self._reveal
        if overlay is not None and overlay.active:
            try:
                return fg == int(overlay.winId())
            except Exception:
                return False
        return False
