# -*- coding: utf-8 -*-
"""点击托盘后向上展开的电量卡片。

结构：一张卡片，两页切换 —— 设备列表页 / 设置页。
不带任何说明性文案，信息只留设备名与电量。
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import QCursor, QGuiApplication
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
# 窗口边界 == 卡片边界：卡片四周不留投影，轮廓交给卡片自己的 1px 描边。
# 早先给投影留过 22px 边距，46px 的模糊在半路被窗口裁断，四个角成了硬邦邦
# 的黑三角；去掉之后 grab 一张窗口也只要 1ms 左右（以前要跑一遍高斯），
# 换肤动效起手更快。
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

# 托盘图标一定贴着任务栏所在的屏幕边缘。切屏 / 退出全屏游戏之后，
# Shell_NotifyIconGetRect 偶尔会返回屏幕中间的一块矩形（浮出工具栏、
# 输入法候选条之类），照着它落位，卡片就会"自己跑到屏幕中间"。
# 离任何一条屏幕边超过这个距离的锚点一律不认。
TRAY_EDGE = 260
# 图标矩形不可能这么大。有的系统版本在全屏应用前台时会把整条任务栏
# 或整个通知区域丢回来，宽高几百像素 —— 那种矩形也不能当锚点，
# 否则卡片会按"任务栏中心"落位，看起来就是跑到了屏幕中间。
TRAY_MAX = 96
# 位置巡检周期。只在卡片可见时跑，一次比较两个整数，成本可以忽略。
ANCHOR_WATCH_MS = 700
# 外部把窗口搬走多少像素才纠回。入场动画本身只移动 10px，
# 阈值取 24 既不会跟动画打架，又能抓住 DPI 变化那种上百像素的跳动。
ANCHOR_DRIFT = 24
# 换肤盖板（卡片上的子控件）的看门狗。正常动效 780ms 结束；超过这个
# 时间还挂着，说明换肤链路中途断了（异常 / 窗口被隐藏），必须强制收掉 ——
# 否则旧皮肤会一直冻在卡片上，看着像"换了没生效"。
REVEAL_WATCHDOG_MS = 1500
# 点完换肤/毛玻璃之后的"免收起"宽限期。动效 780ms，留一点余量；
# 悬停弹出的卡片没有前台身份，任何一次失活误判都会把正在播的卡片抽走。
INTERACT_GRACE = 1.2


def tray_rect_ok(rect: QRect | None) -> bool:
    """这个矩形像不像一枚托盘图标。"""
    if rect is None or rect.isNull():
        return False
    if rect.width() <= 0 or rect.height() <= 0:
        return False
    return rect.width() <= TRAY_MAX and rect.height() <= TRAY_MAX


def _windows_api():
    """user32 / kernel32。延迟导入，模块加载时不碰 Win32。"""
    import ctypes

    return ctypes.windll.user32, ctypes.windll.kernel32


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
        # 托盘锚点。原先只存了 anchor_x / anchor_bottom 两个数字，一旦
        # Windows 在切分辨率、独占全屏退出、DPI 变化之后把顶层窗口重新
        # 摆到屏幕中间，就再也没人把它拉回来。现在记住整块托盘矩形，
        # 并定期核对窗口位置。
        self._anchor = QRect()
        self._placing = False
        self._anchor_watch = QTimer(self)
        self._anchor_watch.setInterval(ANCHOR_WATCH_MS)
        self._anchor_watch.timeout.connect(self._keep_anchor)
        self._reveal_gen = 0
        self._screens_hooked = False
        # 最后一次"人在卡片里动手"的时刻（换肤/毛玻璃动效的起手）。
        # 见 _confirm_deactivate：这之后的一小段时间里不许自动收起。
        self._interact_stamp = 0.0

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("外设电量")
        self.setStyleSheet(theme.qss())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
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
        self._hook_screens()

    # ---------------- 锚点 ----------------
    def _hook_screens(self) -> None:
        """屏幕几何 / DPI 一变就重新落位。

        全屏游戏切出来、改分辨率、换缩放比例，Windows 都会给顶层窗口
        发 WM_DPICHANGED，并附上一个"建议矩形"——那个矩形往往就在屏幕
        中间，Qt 会照单全收。卡片贴托盘的位置是算出来的，不能交给系统，
        所以这里盯住屏幕信号，一变就按锚点重新摆。
        """
        if self._screens_hooked:
            return
        self._screens_hooked = True
        for screen in QGuiApplication.screens():
            self._watch_screen(screen)
        app = QGuiApplication.instance()
        if app is not None:
            try:
                app.screenAdded.connect(self._watch_screen)
            except Exception:
                pass

    def _watch_screen(self, screen) -> None:
        if screen is None:
            return
        for sig in (screen.geometryChanged, screen.availableGeometryChanged,
                    screen.logicalDotsPerInchChanged):
            try:
                sig.connect(self._on_screen_changed)
            except Exception:
                pass

    def _on_screen_changed(self, *_args) -> None:
        if self.isVisible():
            QTimer.singleShot(0, self._reposition)

    def _default_anchor(self, screen=None) -> QRect:
        """没有可信托盘矩形时：光标所在屏幕的右下角。

        取光标而不是主屏：多显示器下任务栏常在副屏，退回主屏会让卡片
        出现在另一块屏幕上，用户以为"点不出来"。
        """
        if screen is None:
            screen = (QGuiApplication.screenAt(QCursor.pos())
                      or QGuiApplication.screenAt(self.frameGeometry().center())
                      or QGuiApplication.primaryScreen())
        geo = screen.availableGeometry()
        return QRect(geo.right() - 56, geo.bottom() - 44, 24, 24)

    def _anchor_for(self, rect: QRect | None) -> QRect:
        """把托盘矩形变成可信锚点：必须是"一枚图标"，且贴着屏幕边缘。"""
        if not tray_rect_ok(rect):
            return self._default_anchor()
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        edge = min(abs(rect.left() - geo.left()), abs(rect.top() - geo.top()),
                   abs(rect.right() - geo.right()), abs(rect.bottom() - geo.bottom()))
        if edge > TRAY_EDGE:
            # Shell 给错了：不当它是托盘图标，退回屏幕角落
            return self._default_anchor(screen)
        return QRect(rect)

    def _place_point(self) -> QPoint | None:
        """按锚点算窗口左上角。锚点为空（还没 show 过）时返回 None。"""
        anchor = self._anchor
        if anchor.isNull() or anchor.width() <= 0:
            return None
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = self._clamp_x(anchor.center().x() - w // 2, w, geo)
        # 任务栏在下（最常见）：底边贴着图标上方，内容变高时向上生长。
        # 任务栏在上：反过来，卡片从图标下方展开，否则会整块翻到屏幕外。
        if anchor.center().y() >= geo.center().y():
            y = anchor.top() - SHADOW_GAP - h
        else:
            y = anchor.bottom() + SHADOW_GAP
        y = max(geo.top() + 8, min(y, geo.bottom() - h - 8))
        return QPoint(x, y)

    def _keep_anchor(self) -> None:
        """巡检：窗口被外部搬走（多半是 DPI 变化）就拉回托盘旁边。"""
        if not self.isVisible() or self._placing:
            return
        anim = self._pos_anim
        if anim is not None and anim.state() == QAbstractAnimation.Running:
            return                       # 入场动画自己会收敛，别插手
        point = self._place_point()
        if point is None:
            return
        if abs(self.x() - point.x()) > ANCHOR_DRIFT or abs(self.y() - point.y()) > ANCHOR_DRIFT:
            self._reposition()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._anchor_watch.start()

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._anchor_watch.stop()
        super().hideEvent(ev)

    # ---------------- 头部 ----------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(2)
        row.setContentsMargins(0, 0, 0, 0)

        # 列表页不再显示"键盘/鼠标"这类类型标题：一台设备时它就是废话，
        # 多台时也没人靠它认设备。标题只留给设置页做页面名。
        self.header_label = QLabel("")
        self.header_label.setObjectName("HeaderLabel")
        self.header_label.setVisible(False)
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
        self._interval_group = QButtonGroup(page)
        self._interval_group.setExclusive(True)
        block, self.interval_note = self._chip_block(
            "刷新间隔 · 分钟", [(m, str(m)) for m in INTERVALS],
            self._pick_interval, self._chips,
            note="（上次刷新 —）", group=self._interval_group,
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
        # 间隔必须始终有一个选中项。再点当前项时先把选中态拉回来，不写成空。
        self._sync_chips()
        if minutes == self.config.interval_minutes:
            return
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
        region = QRect(self.pos(), self.card.size()).adjusted(
            -BACKDROP_SIDE, -BACKDROP_TOP, BACKDROP_SIDE, BACKDROP_SIDE)
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
        self.header_label.setVisible(self._settings_open)
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
    def apply_theme(self) -> None:
        """全局换肤后刷新自身与所有子控件。

        动效盖板由 _pick_theme 提前盖好，圆心取自被点中的那个选项框。
        窗口没显示、或截不到图时静静走普通切换，不播动效。

        这里必须保证 _finish_reveal 一定被执行：中途抛异常（某一行控件、
        某个字体度量）就退出的话，盖板会停在原地不动 —— 屏幕上就是一张
        冻住的旧皮肤，收不收得掉只能等看门狗，观感等于"点了没反应"。
        """
        try:
            self.setStyleSheet(theme.qss())
            self._sync_theme_chips()
            for row in self._rows.values():
                try:
                    row.apply(row.device, animate=False)
                except Exception:
                    pass
            self.card.update()
            self.update()
            # 换色不该改尺寸，但真变了（字体回退）就得重排；同时顺手核对
            # 一次位置 —— 切屏/DPI 变化可能刚把窗口搬到别处。
            if self.sizeHint() != self.size():
                self._relayout()
            if self.isVisible():
                self._reposition()
        finally:
            self._sync_overlay()
            self._finish_reveal()

    # ---------------- 换肤动效 ----------------
    def _card_snapshot(self):
        """截一张卡片本体。

        窗口边界 == 卡片边界，整窗截图就是卡片本体，不需要再裁剪。

        盖板现在是卡片的子控件，抓图前必须先把它藏一瞬（否则抓到的就是
        盖板里那张旧图，新皮肤永远揭不开）。藏→抓→显示全在同一个事件里，
        中间不会回到事件循环，屏幕上不会闪。
        """
        if not self.isVisible():
            return None
        overlay = self._reveal
        hidden = overlay is not None and overlay.active and not overlay.isHidden()
        if hidden:
            overlay.hide()
        try:
            pm = self.grab()
        finally:
            if hidden and overlay.active:
                overlay.show()
                overlay.raise_()
        if pm is None or pm.isNull():
            return None
        return pm

    def _start_reveal(self, origin: QPoint | None) -> RevealOverlay | None:
        """第一步：趁皮肤还没换，截旧图、盖盖板。

        盖板贴的就是旧皮肤，所以从它出现到揭开之间，屏幕上始终是旧皮肤
        或"旧皮肤被圆一点一点换成新皮肤"，不会闪出一张裸的新皮肤。

        `origin` 拿不到（控件还没布局、已经滚出视图）不算失败 —— 退回
        卡片中心继续播。宁可圆心偏一点，也不要"点了没反应"。
        """
        self._drop_reveal()
        if not self.isVisible():
            return None
        if origin is None:
            origin = QPoint(self.card.width() // 2, self.card.height() // 2)
        # 记一下"人刚在卡片里点过东西"：接下来一秒多里谁都不许把卡片收起。
        # 悬停弹出的卡片本来就没抢到前台，别的应用一抢焦点就会走到
        # _confirm_deactivate，一次误判就能把正在播动效的卡片抽走。
        self._interact_stamp = time.monotonic()
        try:
            before = self._card_snapshot()
        except Exception:
            before = None
        if before is None or before.isNull():
            return None
        try:
            overlay = RevealOverlay(self.card, before, origin,
                                    on_closed=self._on_reveal_closed)
        except Exception:
            return None
        if not overlay.active:
            return None
        self._reveal = overlay
        self._reveal_gen += 1
        gen = self._reveal_gen
        # 看门狗：盖板亮着但动画没起来的任何情况，到点强制收掉。
        # 它是子控件、不吃鼠标，所以收不掉也不会点不动；这道保险防的是
        # "旧皮肤一直冻在卡片上"，那看起来就像换肤没生效。
        QTimer.singleShot(REVEAL_WATCHDOG_MS, lambda: self._reveal_timeout(gen))
        # 旧皮肤必须先真正画到屏幕上，再换肤；这里用 repaint 同步重绘，
        # 不用 processEvents —— 后者会把排队的鼠标事件（包括这次点击的
        # 抬起、下一次点击）在按钮的处理函数里重入进来，是"点完按钮状态
        # 卡住、后面点不动"的典型来源。
        try:
            overlay.repaint()
        except Exception:
            pass
        return overlay

    def _reveal_timeout(self, gen: int, retries: int = 3) -> None:
        overlay = self._reveal
        if gen != self._reveal_gen or overlay is None or not overlay.active:
            return
        if overlay.animating() and retries > 0:
            # 动效在播，给它收尾的时间（正常 780ms 内必结束）。
            # 只多等 3 轮：真卡死的动画不应该被无限期放过。
            QTimer.singleShot(400, lambda: self._reveal_timeout(gen, retries - 1))
            return
        self._drop_reveal()

    def _on_reveal_closed(self, overlay) -> None:
        # 盖板播完自毁后第一时间松手，别攥着一个已删除的 C++ 包装
        if self._reveal is overlay:
            self._reveal = None

    def reveal_active(self) -> bool:
        """换肤盖板是否还活着（正在播 / 还没收尾）。"""
        overlay = self._reveal
        return overlay is not None and overlay.active

    def _finish_reveal(self) -> None:
        """第二步：皮肤已换完。截新图、开始圆形揭开。

        盖板是卡片自己的子控件，没盖满就拿旧图去揭会露边，所以先让它
        对齐新的卡片尺寸，再截新图。
        """
        overlay = self._reveal
        if overlay is None or not overlay.active:
            self._drop_reveal()
            return
        if not self.isVisible():
            self._drop_reveal()
            return
        # grab() 是同步渲染，不依赖屏幕刷新，也不必 processEvents；
        # 先把新皮肤画出来再截，图才是新的。
        try:
            self._sync_overlay()
            self.repaint()
            overlay.set_new_and_start(self._card_snapshot())
        except Exception:
            self._drop_reveal()

    def _drop_reveal(self) -> None:
        self._reveal_gen += 1          # 作废所有在路上的看门狗
        overlay = self._reveal
        self._reveal = None
        if overlay is not None and overlay.active:
            try:
                overlay.close_reveal()
            except Exception:
                pass

    def _sync_overlay(self) -> None:
        overlay = self._reveal
        if overlay is not None and overlay.active:
            if not overlay.isVisible():
                overlay.show()
                overlay.raise_()
            overlay.sync_geometry()

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

        # 走一遍列表：缺的补上、有的就地更新、位置不对的搬过去。
        # 以前拆成"先建后排序"两轮，顺序纠正那一轮还要再查一次 indexOf，
        # 同一台设备被碰两次；现在一轮解决，动画也不会重复触发。
        for index, device in enumerate(devices):
            row = self._rows.get(device.key)
            if row is None:
                row = DeviceRow(device, animate=animate)
                self._rows[device.key] = row
            else:
                row.apply(device, animate=animate)
                if self.devices_box.indexOf(row) == index:
                    continue
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
        if self.interval_note is not None:
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

    @staticmethod
    def _sync_switch(switch: ToggleSwitch, on: bool) -> None:
        """把开关拨到配置值，但不触发 toggled（否则会回写一遍配置）。"""
        switch.blockSignals(True)
        switch.setChecked(on)
        switch.set_knob(1.0 if on else 0.0)
        switch.blockSignals(False)

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
            self._sync_switch(self.glass_switch, glass)
            self._sync_switch(self.autostart_switch, bool(self.config.get("autostart")))
        finally:
            self._syncing = False

    # ---------------- 窗口行为 ----------------
    def hidden_recently(self, seconds: float) -> bool:
        """刚刚才收起过吗（托盘连点去抖、悬停重开防抖共用）。"""
        return time.monotonic() - self._hide_stamp < seconds

    def show_near(self, tray_rect: QRect, activate: bool = True) -> None:
        """显示卡片。activate=False 用于悬停弹出：只出现，不抢当前窗口的焦点。"""
        self._relayout()
        self.resize(self.sizeHint())

        # 锚点先过一遍合法性：游戏中切屏后 Shell 可能给回一块屏幕中间的
        # 矩形，照它落位卡片就会"跑到屏幕中间"。不合法的锚点退回屏幕角。
        self._anchor = self._anchor_for(tray_rect)
        point = self._place_point()
        if point is None:
            self._anchor = self._default_anchor()
            point = self._place_point() or QPoint(0, 0)
        x, y = point.x(), point.y()

        # 上一轮的 hide 动画可能还在播（isVisible() 仍为 True）。这时抓底图
        # 抓到的是卡片自己（毛玻璃退回实底），落位也会按旧尺寸算，
        # 所以重开前先把窗口真正藏掉。盖板（卡片的子控件）一起收掉：
        # 重新弹出是从"没有盖板"的状态开始的。
        self._drop_reveal()
        if self.isVisible():
            if self._hide_anim is not None:
                self._hide_anim.stop()
            self.hide()

        self.setWindowOpacity(0.0)
        self._placing = True
        try:
            self.move(x, y + 10)
        finally:
            self._placing = False

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
            self._force_foreground()

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

    def _force_foreground(self) -> None:
        """把卡片真正提到前台。

        全屏游戏或别的应用占着前台时，Qt 的 activateWindow() 会被 Windows
        拒绝（前台锁定）。卡片虽然置顶显示，鼠标点击却仍然落进游戏，
        表现就是"卡片弹出来了，但点什么都没反应"。这里借前台线程的输入
        队列把 SetForegroundWindow 发出去 —— 只在用户明确点托盘图标
        （activate=True）时调用，悬停弹出绝不抢焦点。
        """
        try:
            user32, kernel32 = _windows_api()
            hwnd = int(self.winId())
            fg = int(user32.GetForegroundWindow())
            if fg == hwnd:
                return
            tid_fg = int(user32.GetWindowThreadProcessId(fg, None)) if fg else 0
            tid_me = int(kernel32.GetCurrentThreadId())
            attached = False
            if tid_fg and tid_fg != tid_me:
                attached = bool(user32.AttachThreadInput(tid_me, tid_fg, True))
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(tid_me, tid_fg, False)
        except Exception:
            pass

    @staticmethod
    def _clamp_x(x: int, w: int, geo) -> int:
        return max(geo.left() + 8, min(x, geo.right() - w - 8))

    def _reposition(self) -> None:
        point = self._place_point()
        if point is None:
            return
        # 入场位移动画记的是"展开那一刻的高度"算出的坐标。页面变高（比如刚切到
        # 设置页）时它还在播，就会一帧一帧把窗口拉回下面的旧位置——表现为
        # "第一次打开设置，弹窗往下掉"。内容一变就让动画先退场，落位以新高度为准。
        anim = self._pos_anim
        if anim is not None and anim.state() == QAbstractAnimation.Running:
            anim.stop()
            self._pos_anim = None
        if (self.x(), self.y()) == (point.x(), point.y()):
            return
        self._placing = True
        try:
            self.move(point)
        finally:
            self._placing = False

    def resizeEvent(self, ev) -> None:  # noqa: N802
        # 盖板是卡片的子控件，挪窝它自己会跟着走；但尺寸不会跟着长，
        # 得手动铺满，否则圆揭到边上会露出新皮肤的一条边。
        self._sync_overlay()
        super().resizeEvent(ev)

    def hide_card(self) -> None:
        if not self.isVisible():
            return

        self._hide_stamp = time.monotonic()
        # 卡片要没了，盖板没有继续存在的意义（同时作废挂着的看门狗）
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

        为什么不能收到 WindowDeactivate 就藏：换肤时整窗重刷、卡片被系统
        重新摆位、盖板（现在是子控件，以前是顶层窗口）出现，都可能让
        Windows 给卡片补一个 WA_INACTIVE（Qt 就翻译成 WindowDeactivate），
        可前台窗口其实一直是卡片自己。此时若照旧 hide_card，表现就是
        "点一下颜色，卡片瞬间消失"。

        所以这里做三件事：
        1. 延后 140ms 再判断，把同一轮的连串假失活折叠掉；
        2. 用原生前台窗口核对 —— 前台还是卡片就说明是假信号，不动；
           盖板还在播动效时也先不动（把卡片藏了，动效就被剪断了）；
        3. 光标还压在卡片上就说明没人去点别处，同样按噪声丢掉 ——
           点完颜色/开关那一瞬间，鼠标必定还在卡片里。
        """
        if gen != self._deactivate_gen or not self.isVisible():
            return                     # 已有更新的一轮判断，交给它
        if self._suppress_hide:
            return
        if self.reveal_active() and tries < 16:
            # 盖板还在（最多 780ms 动效 + 收尾），等它播完再核实，
            # 否则卡片可能在"圆还没揭开"时就没了
            self._sync_overlay()
            QTimer.singleShot(120, lambda: self._confirm_deactivate(gen, tries + 1))
            return
        if self._foreground_is_ours():
            return
        # 刚点过换肤/毛玻璃：动效还在路上。悬停弹出的卡片本来就没有前台
        # 身份，这段时间里的失活一律当噪声 —— 一收起来，盖板上那张旧皮
        # 就得孤零零留在屏幕上，动效也跟着没了。但不吞掉这次判断：
        # 等宽限期过完再核实一遍，用户真去点别处时卡片照样会收。
        wait = INTERACT_GRACE - (time.monotonic() - self._interact_stamp)
        if wait > 0 and tries < 8:
            QTimer.singleShot(int(wait * 1000) + 40,
                              lambda: self._confirm_deactivate(gen, tries + 1))
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
            return self.frameGeometry().adjusted(-4, -4, 4, 4).contains(QCursor.pos())
        except Exception:
            return False

    def _foreground_is_ours(self) -> bool:
        """原生前台窗口是不是本卡片。

        换肤盖板现在是卡片的子控件，不再单独占一个顶层窗口，所以前台
        只可能是卡片自己 —— 早先那种"盖板一出现就给卡片补一个假失活"
        的来源也随之消失。这里仍然直接问系统：Qt 的 isActiveWindow()
        在无边框工具窗口上有时候会记账记错。
        """
        try:
            user32, _kernel32 = _windows_api()
            fg = int(user32.GetForegroundWindow())
        except Exception:
            return False
        if not fg:
            return False                 # 查不到就别当"还是自己"，交给下面按失焦处理
        try:
            return fg == int(self.winId())
        except Exception:
            return False
