# -*- coding: utf-8 -*-
"""程序入口：托盘常驻 + 定时扫描 + 低电量提醒。"""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from PySide6.QtCore import QRect, QTime, QTimer, Qt, QThread, Signal          # noqa: E402
from PySide6.QtGui import QAction, QCursor, QIcon                             # noqa: E402
from PySide6.QtWidgets import (                                               # noqa: E402
    QApplication, QMenu, QMessageBox, QSystemTrayIcon,
)

import theme                                                                  # noqa: E402
from config import (                                                          # noqa: E402
    APP_NAME, Config, apply_autostart_preference, autostart_enabled, set_autostart,
)
from model import Device                                                      # noqa: E402
from scanner import Scanner                                                   # noqa: E402
from trayhover import TrayHover                                               # noqa: E402
from ui import icons                                                          # noqa: E402
from ui.card import CardWindow, tray_rect_ok                                  # noqa: E402
from ui.diag import DiagWindow                                                # noqa: E402

# 充电时的自动刷新间隔：用户设的 10/15/20 分钟是给"不充电、省电"用的，
# 充电中电量涨得快，还按原来的节奏卡片会明显落后于厂商驱动（插着电也不怕耗电）。
# 30 秒：充电时大约 1 分钟涨 1%，半分钟一读基本做到"驱动显示多少这里就是多少"。
# 注意 providers/evision.py 的 COOLDOWN 必须严格小于它，否则会被判成"仍在冷却"
# 而复用旧值 —— 那正是 1.5.11 之前读数滞后的原因。
CHARGE_REFRESH_MS = 30_000


class ScanWorker(QThread):
    done = Signal(list, list, str)

    def __init__(self, config: Config, with_debug: bool = False,
                 force: bool = False, parent=None):
        super().__init__(parent)
        self.config = config
        self.with_debug = with_debug
        self.force = force

    def run(self) -> None:
        try:
            scanner = Scanner(self.config)
            devices, debug = scanner.scan(with_debug=self.with_debug, force=self.force)
            self.done.emit(devices, debug, "")
        except Exception as exc:  # 兜底，避免线程异常吞掉界面更新
            self.done.emit([], [], f"{type(exc).__name__}: {exc}")


class TrayApp:
    def __init__(self, app: QApplication):
        self.app = app
        self.config = Config()
        self.devices: list[Device] = []
        self.debug_lines: list[str] = []
        self._worker: ScanWorker | None = None
        # 逻辑上的"这一轮扫描还在跑"。跟 _worker 分开记：线程对象要活到
        # finished 才算完（运行中被回收 Qt 会 abort），而按钮/定时器要的
        # 是「结果到了没有」，两者差一拍。
        self._scanning = False
        self._diag: DiagWindow | None = None
        # 充电动画：预渲染的几帧图标 + 轮换定时器
        self._tray_frames: list[QIcon] = []
        self._tray_frame = 0
        self._tray_key: tuple | None = None

        # 配色先落地，后续所有控件都按当前主题构建
        theme.set_mode(str(self.config.get("theme") or "dark"))
        app.setStyleSheet(theme.qss())

        # 自启以配置为准，启动时纠正注册表（安装时未勾选就该是关闭）
        real = apply_autostart_preference(bool(self.config.get("autostart")))
        if bool(self.config.get("autostart")) != real:
            self.config.set("autostart", real)

        self.tray = QSystemTrayIcon(self._tray_icon(None))
        self.tray.setToolTip("外设电量 · 正在读取…")
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.card = CardWindow(self.config)
        self.card.refresh_requested.connect(lambda: self.refresh(manual=True))
        self.card.interval_changed.connect(self._on_interval_changed)
        self.card.autostart_changed.connect(self._on_autostart_changed)
        self.card.theme_changed.connect(self._on_theme_changed)
        self.card.diag_requested.connect(self.open_diag)
        self.card.sync_from_config()

        self.tray_pulse = QTimer()
        self.tray_pulse.setInterval(140)   # 14 帧 × 140ms ≈ 2.0s 从空充满一次
        self.tray_pulse.timeout.connect(self._next_tray_frame)

        # 悬停托盘图标直接弹卡片（原生 tooltip 只有一行字，信息太少）
        self.hover = TrayHover(self.tray, self.card)
        self.hover.supported_changed.connect(self._on_hover_support)
        self.hover.start()

        self.timer = QTimer()
        self.timer.setInterval(self.config.interval_ms)
        self.timer.timeout.connect(lambda: self.refresh())
        self.timer.start()

        # 首次读取走静默扫描：没点过按钮，就不该出现"完成对勾"。
        # 不传 force：进程刚起，各通道的缓存都是空的，本来就会真去读；
        # 而 force 会让 Evision 直接走慢协议窗口，普通键盘白等十几秒。
        QTimer.singleShot(250, lambda: self.refresh())

    # ---------------- 菜单 ----------------
    def _build_menu(self) -> QMenu:
        menu = QMenu()
        act_refresh = QAction("立即刷新", menu)
        act_refresh.triggered.connect(lambda: self.refresh(manual=True))
        menu.addAction(act_refresh)

        act_settings = QAction("打开设置", menu)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)

        menu.addSeparator()

        self.act_autostart = QAction("开机自启动", menu)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(autostart_enabled())
        self.act_autostart.triggered.connect(self._on_menu_autostart)
        menu.addAction(self.act_autostart)

        act_diag = QAction("设备诊断", menu)
        act_diag.triggered.connect(self.open_diag)
        menu.addAction(act_diag)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)
        return menu

    def _open_settings(self) -> None:
        # 先切页面、再展开：顺序反了的话入场动画是按列表页高度算的位置，
        # 设置页更高，窗口就会往下掉一截（第一次从菜单打开设置时的那个下移）
        if not self.card._settings_open:
            self.card.toggle_settings()
        self.show_card()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.card.isVisible():
                self.hover.mute()
                self.card.hide_card()
                return
            # 失焦自动隐藏与再次点击可能同帧发生，做一次去抖
            if self.card.hidden_recently(0.35):
                return
            self.show_card()

    def show_card(self) -> None:
        rect = self.tray.geometry()
        if not tray_rect_ok(rect):
            # 图标被折进「^」/ 任务栏自动隐藏 / 全屏游戏切回来时拿不到
            # 可信矩形：退到光标所在屏幕的右下角。原来是 primaryScreen，
            # 多显示器下会弹到另一块屏；拿整条任务栏当锚点则会跑到屏幕中间。
            screen = self.app.screenAt(QCursor.pos()) or self.app.primaryScreen()
            geo = screen.availableGeometry()
            rect = QRect(geo.right() - 56, geo.bottom() - 40, 24, 24)
        self.card.show_near(rect)

    # ---------------- 图标与提示 ----------------
    @staticmethod
    def _tray_device(devices: list[Device] | None) -> Device | None:
        """托盘图标代表哪台设备：电量最低的那台。

        多台设备共用一个托盘格，塞不下每台一个格子（16px 里切格必然糊成一团），
        所以只报最该看的那台 —— 电量最低的就是最需要充电的。每台的明细
        在卡片和悬浮提示里都有。
        """
        known = [d for d in (devices or []) if d.level is not None]
        if known:
            return min(known, key=lambda d: d.level)
        return (devices or [None])[0]

    def _tray_icon(self, devices: list[Device] | None) -> QIcon:
        ink = theme.tray_icon_color()
        dev = self._tray_device(devices)
        if dev is None:
            return icons.tray_icon(None, ink)
        return icons.tray_icon(dev.level, ink)

    def _update_tray_icon(self) -> None:
        """按当前设备刷新托盘图标；正在充电就切成绿色流动动画。"""
        dev = self._tray_device(self.devices)
        # 只有"电量 / 充电"变化时才重建帧。图标颜色固定，不再跟主题走，
        # 所以主题切换不需要重建（切主题处仍会重置 key，无害）。
        key = None if dev is None else (dev.level, bool(dev.charging))
        if key == self._tray_key:
            return
        self._tray_key = key

        self.tray_pulse.stop()
        self._tray_frames = []
        self._tray_frame = 0

        if dev is not None and dev.charging:
            self._tray_frames = icons.tray_charge_frames(
                theme.tray_icon_color(), theme.tray_charge_color())
            self.tray.setIcon(self._tray_frames[0])
            self.tray_pulse.start()
        else:
            self.tray.setIcon(self._tray_icon(self.devices))

    def _next_tray_frame(self) -> None:
        if not self._tray_frames:
            self.tray_pulse.stop()
            return
        self._tray_frame = (self._tray_frame + 1) % len(self._tray_frames)
        self.tray.setIcon(self._tray_frames[self._tray_frame])

    def _tooltip(self) -> str:
        if not self.devices:
            return "未检测到无线外设"
        lines = []
        for dev in self.devices:
            if dev.level is None:
                note = ("不提供电量"
                        if (dev.raw or {}).get("state") == "无电量接口" else "未读到")
                lines.append(f"{dev.name}  --  {note}")
            else:
                mark = " · 充电中" if dev.charging else ""
                lines.append(f"{dev.name}  {dev.percent_text}%{mark}")
        return "\n".join(lines)

    def _on_hover_support(self, _ok: bool) -> None:
        # 悬停可用与否只影响"要不要显示原生文字提示"，见 _sync_tooltip
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        """能靠悬停弹卡片时就把原生那一行提示清掉。

        两套提示同时出现会"文字卡片一闪一闪"，而且原生 tooltip 长得跟
        卡片完全不搭。图标被折进「^」里、悬停不可用时再退回文字。
        """
        text = "" if self.hover.supported else self._tooltip()
        if self.tray.toolTip() != text:
            self.tray.setToolTip(text)

    # ---------------- 刷新 ----------------
    def refresh(self, manual: bool = False, force: bool | None = None) -> None:
        if self._scanning:
            return
        if force is None:
            force = manual
        if manual:
            self.card.set_loading(True)
        worker = ScanWorker(self.config, with_debug=False, force=force)
        worker.done.connect(self._on_scan_done)
        # 线程真正结束后再释放引用：done 到达时线程可能还没退完，
        # 这时候换下一位会让 QThread 在运行中被析构（Qt 直接 abort）。
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._scanning = True
        self._worker = worker
        worker.start()

    def _on_worker_finished(self, worker) -> None:
        if worker is not None:
            worker.deleteLater()
        if self._worker is worker:
            self._worker = None
        # 线程都退完了，这一轮一定结束了。万一 done 没送到（异常路径），
        # 这里兜住：否则 _scanning 永远是 True，之后再也刷不动。
        self._scanning = False

    def _on_scan_done(self, devices: list, debug: list, error: str) -> None:
        self._scanning = False
        self.devices = devices
        if debug:
            self.debug_lines = debug
        self.card.set_loading(False)
        self.card.set_last_refresh(QTime.currentTime().toString("HH:mm"))
        self.card.set_devices(self.devices, error or None)
        self._update_tray_icon()
        self._sync_tooltip()
        self._sync_timer_interval()
        if self._diag:
            self._diag.update_devices(self.devices, self.debug_lines)
        # 刷新刚建出来的枚举表和线程池，用完就还给系统，不留在这一轮里
        gc.collect()

    def _sync_timer_interval(self) -> None:
        """按"是否在充电"决定下一次自动刷新的间隔。"""
        charging = any(bool(d.charging) for d in self.devices)
        ms = CHARGE_REFRESH_MS if charging else self.config.interval_ms
        if self.timer.interval() != ms:
            self.timer.setInterval(ms)

    # ---------------- 设置联动 ----------------
    def _on_interval_changed(self, _minutes: int) -> None:
        # 间隔已经写进 config，这里只按"是否充电"重算定时器
        self._sync_timer_interval()

    def _on_menu_autostart(self, checked: bool) -> None:
        self._on_autostart_changed(bool(checked))

    def _on_autostart_changed(self, checked: bool) -> None:
        self.config.set("autostart", bool(checked))
        set_autostart(bool(checked))
        real = autostart_enabled()
        self.config.set("autostart", real)
        self.act_autostart.blockSignals(True)
        self.act_autostart.setChecked(real)
        self.act_autostart.blockSignals(False)
        self.card.sync_from_config()
        if checked and not real:
            self.tray.showMessage(
                "开机自启设置失败",
                "无法写入注册表启动项，请检查安全软件拦截。",
                QSystemTrayIcon.Warning, 5000,
            )

    def _on_theme_changed(self, mode: str) -> None:
        theme.set_mode(mode)
        self.app.setStyleSheet(theme.qss())
        self.card.apply_theme()
        # 托盘图标配色已固定（不随深浅主题变化），这里不用重建图标
        if self._diag:
            self._diag.apply_theme()

    # ---------------- 诊断 ----------------
    def open_diag(self) -> None:
        if self._diag is None:
            self._diag = DiagWindow(self.config)
            self._diag.rule_changed.connect(lambda: self.refresh(manual=True))
        self._diag.update_devices(self.devices, self.debug_lines)
        self._diag.show()
        self._diag.raise_()
        self._diag.activateWindow()

    def quit(self) -> None:
        self.timer.stop()
        self.hover.stop()
        self.tray_pulse.stop()
        # 扫描线程还在跑就别让它被析构：QThread 在运行中被销毁，Qt 会
        # 直接 abort（用户看到的是"退出时闪一下报错"）。等一小会儿，
        # 等不到就结束进程 —— 配置文件早已落盘，没有未保存状态。
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(1200)
            if worker.isRunning():
                self.tray.hide()
                os._exit(0)
        self.tray.hide()
        self.app.quit()


def acquire_single_instance() -> bool:
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(APP_NAME)
    if socket.waitForConnected(250):
        socket.disconnectFromServer()
        return False
    QLocalServer.removeServer(APP_NAME)
    server = QLocalServer()
    server.listen(APP_NAME)
    globals()["_instance_server"] = server  # 保活
    return True


def main() -> int:
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(icons.app_icon(64)))

    if not acquire_single_instance():
        QMessageBox.information(None, APP_NAME, "程序已在运行，请在任务栏右下角查看。")
        return 0

    tray_app = TrayApp(app)
    globals()["_tray_app"] = tray_app
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
