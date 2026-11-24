# -*- coding: utf-8 -*-
"""设备诊断：一个按钮，自动把能读到的设备都找出来。

旧版是一张端点表 + 复制 + 粘贴 + 识别，要求用户先看懂"页面 0xFF00、
用法 0x0002"才知道该复制哪一行 —— 实际反馈是绝大多数人卡在这一步。
现在页面只留一个动作：

    [ 开始自动诊断 ]  →  进度条走动 + 底部「识别中，请勿关闭」
                     →  上面列出读到的设备，下面列出读不到的和原因

读不到的仍然可以「导出诊断报告」，但那是备用通道，不再是使用前提。
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths, QThread, Signal
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import autodiag
import theme
from config import APP_VERSION, Config
from model import Device
from providers import raw_hid, xinput_pad
from ui.adddevice import AddDeviceWindow
from vendors import describe as describe_vendor


class AutoDiagWorker(QThread):
    """扫描 + 被动监听都在这里跑，UI 线程只负责画进度。"""

    progress = Signal(str, int)
    done = Signal(dict)

    def __init__(self, config: Config, mode: str = "diag", parent=None):
        super().__init__(parent)
        self.config = config
        self.mode = mode
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            if self.mode == "refresh":
                result = autodiag.scan_only(self.config)
                result["mode"] = self.mode
                self.done.emit(result)
                return
            result = autodiag.run(
                self.config,
                progress=lambda text, pct: self.progress.emit(text, pct),
                stop=self._stop,
            )
            if self.mode == "report":
                result["endpoints_list"] = raw_hid.describe_endpoints()
                try:
                    result["xinput"] = xinput_pad.describe()
                except Exception as exc:
                    result["xinput"] = [f"XInput 读取失败: {type(exc).__name__}: {exc}"]
        except Exception as exc:
            result = {
                "error": f"{type(exc).__name__}: {exc}",
                "devices": [], "failed": [], "rules": 0,
                "endpoints": 0, "seconds": 0.0, "logs": [],
            }
        result["mode"] = self.mode
        self.done.emit(result)


def _style_table(t: QTableWidget) -> None:
    """表格配色交给主题：QSS 管外观，palette 兜住文字色。

    只靠 QSS 的 `QTableWidget::item { color }` 不够稳（不同 Qt 版本、
    不同 delegate 路径下 item 文字会退回 palette 的 Text 色），
    深色主题里那张"黑底黑字"就是这么来的。
    """
    pal = t.palette()
    soft = theme.color(theme.BG_SOFT)
    text = theme.color(theme.TEXT)
    pal.setColor(QPalette.Base, soft)
    pal.setColor(QPalette.AlternateBase, soft)
    pal.setColor(QPalette.Window, soft)
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.Highlight, theme.color(theme.BG_ROW_HOVER))
    pal.setColor(QPalette.HighlightedText, text)
    pal.setColor(QPalette.PlaceholderText, theme.color(theme.TEXT_DIM))
    t.setPalette(pal)
    t.viewport().setPalette(pal)
    t.horizontalHeader().setPalette(pal)
    t.verticalHeader().setPalette(pal)


def _cell(value: str, dim: bool = False, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setForeground(theme.color(theme.TEXT_DIM if dim else theme.TEXT))
    if right:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(30)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(False)
    t.setShowGrid(False)
    t.setFocusPolicy(Qt.NoFocus)
    t.setFrameShape(QTableWidget.NoFrame)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    t.setWordWrap(False)
    t.horizontalHeader().setStretchLastSection(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    _style_table(t)
    return t


class DiagWindow(QWidget):
    rule_changed = Signal()

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self._worker: AutoDiagWorker | None = None
        self._running = False
        self._devices: list[Device] = []
        self._debug: list[str] = []
        self._result: dict | None = None

        self.setWindowTitle("设备诊断")
        self.setMinimumSize(700, 500)
        self.setObjectName("DiagRoot")
        self.setStyleSheet(theme.qss())
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("DiagScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        content = QWidget()
        content.setObjectName("DiagContent")
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # ---------- 顶部：标题 + 唯一按钮 ----------
        header = QHBoxLayout()
        header.setSpacing(10)
        self.head = QLabel("设备诊断")
        self.head.setObjectName("DiagTitle")
        header.addWidget(self.head)
        header.addStretch(1)
        self.add_btn = QPushButton("添加设备")
        self.add_btn.setObjectName("Ghost")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFixedHeight(34)
        self.add_btn.clicked.connect(self._open_add)
        header.addWidget(self.add_btn)
        self.btn = QPushButton("开始自动诊断")
        self.btn.setObjectName("Primary")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(34)
        self.btn.clicked.connect(self._start)
        header.addWidget(self.btn)
        root.addLayout(header)

        self.bar = QProgressBar()
        self.bar.setObjectName("DiagBar")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        root.addWidget(self.bar)

        # ---------- 结果 / 识别中 ----------
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        page_results = QWidget()
        res_lay = QVBoxLayout(page_results)
        res_lay.setContentsMargins(0, 0, 0, 0)
        res_lay.setSpacing(6)

        self.dev_label = QLabel("识别到的设备")
        self.dev_label.setObjectName("SectionLabel")
        res_lay.addWidget(self.dev_label)

        self.dev_table = _table(["设备", "类型", "电量", "读取方式"])
        self.dev_table.setMinimumHeight(150)
        self.dev_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.dev_table.setColumnWidth(2, 76)
        res_lay.addWidget(self.dev_table, 1)

        self.fail_label = QLabel("没能读取")
        self.fail_label.setObjectName("SectionLabel")
        self.fail_label.hide()
        res_lay.addWidget(self.fail_label)

        self.fail_table = _table(["设备", "编号", "原因"])
        self.fail_table.setMinimumHeight(96)
        self.fail_table.setWordWrap(True)
        self.fail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.fail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.fail_table.setColumnWidth(0, 190)
        self.fail_table.setColumnWidth(1, 88)
        self.fail_table.hide()
        res_lay.addWidget(self.fail_table)
        self.stack.addWidget(page_results)
        self._page_results = page_results

        page_busy = QWidget()
        busy_lay = QVBoxLayout(page_busy)
        busy_lay.setContentsMargins(0, 0, 0, 0)
        busy_lay.addStretch(1)
        self.step = QLabel("正在识别…")
        self.step.setObjectName("DiagStep")
        self.step.setAlignment(Qt.AlignCenter)
        self.step.setWordWrap(True)
        busy_lay.addWidget(self.step)
        busy_lay.addStretch(1)
        self.stack.addWidget(page_busy)
        self._page_busy = page_busy

        # ---------- 底部：导出 + 状态 ----------
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.export_btn = QPushButton("导出诊断报告")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setFixedHeight(26)
        self.export_btn.clicked.connect(self._export)
        bottom.addWidget(self.export_btn)
        bottom.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("DiagStatus")
        bottom.addWidget(self.status)
        root.addLayout(bottom)

        self.update_devices([], [])

        hint = content.sizeHint()
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(
            max(700, min(hint.width() + 40, 860)),
            min(max(500, hint.height() + 24), int(avail.height() * 0.88)),
        )

    # ---------------- 状态切换 ----------------
    @property
    def busy(self) -> bool:
        # 用显式标志而不是 QThread.isRunning()：done 信号可能在线程真正
        # 结束前一瞬到达，那时 isRunning() 还是 True，按钮会被误判成"忙"。
        return self._running

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.btn.setEnabled(not busy)
        self.btn.setText("识别中…" if busy else "开始自动诊断")
        self.add_btn.setEnabled(not busy)
        self.export_btn.setEnabled(not busy)
        self.bar.setVisible(busy)
        if busy:
            self.bar.setValue(0)
            self.step.setText(text or "正在识别…")
            self.stack.setCurrentWidget(self._page_busy)
        else:
            self.stack.setCurrentWidget(self._page_results)
            self.bar.setValue(100)

    def _on_progress(self, text: str, pct: int) -> None:
        self.bar.setValue(max(0, min(100, int(pct))))
        self.step.setText(text)
        self.status.setText("识别中，请勿关闭…")

    # ---------------- 主题 ----------------
    def apply_theme(self) -> None:
        """主题切换后重建样式：表格吃 palette，光换 qss 不够。"""
        self.setStyleSheet(theme.qss())
        for table in (self.dev_table, self.fail_table):
            _style_table(table)
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is not None:
                        item.setForeground(theme.color(theme.TEXT))
        self.update()

    # ---------------- 运行 ----------------
    def _start(self) -> None:
        self._run("diag")

    def _run(self, mode: str) -> None:
        if self.busy:
            return
        self._running = True
        self._set_busy(True, "正在识别…")
        self.status.setText("识别中，请勿关闭…")
        self._worker = AutoDiagWorker(self.config, mode=mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, result: dict) -> None:
        self._running = False
        self._set_busy(False)
        self._result = result

        if result.get("error"):
            self.status.setText(f"诊断失败：{result['error']}")
            return

        debug = result.get("logs") or []
        if debug:
            self._debug = debug
        self.update_devices(result.get("devices") or [], [])

        if result.get("mode") == "report":
            self._write_report(result)
            return
        if result.get("mode") == "refresh":
            # 添加设备后只刷新列表，失败表还是上一轮的结论
            self.rule_changed.emit()
            return

        self.status.setText(autodiag.summary(result))
        # 诊断结果要立刻反映到卡片上：本轮的规则已经写进配置，
        # 让主窗口重新扫一遍就能出现在列表里。
        self.rule_changed.emit()

    # ---------------- 添加设备 ----------------
    def _open_add(self) -> None:
        if self.busy:
            return
        known = {d.vid_pid.upper() for d in self._devices if d.vid_pid}
        window = AddDeviceWindow(self.config, known, self)
        window.added.connect(lambda: self._run("refresh"))
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.exec()

    # ---------------- 表格 ----------------
    def update_devices(self, devices: list[Device], debug: list[str]) -> None:
        if self.busy:
            # 自动诊断跑着的时候，主窗口的定时刷新不要来抢表格
            return
        if debug:
            self._debug = list(debug)
        devices = sorted(devices or [], key=lambda d: d.sort_key())
        self._devices = devices

        self.dev_label.setText(f"识别到的设备 · {len(devices)}")
        self.dev_table.setRowCount(max(1, len(devices)))
        if not devices:
            self.dev_table.setItem(0, 0, _cell("暂无", dim=True))
            for col in (1, 2, 3):
                self.dev_table.setItem(0, col, _cell("", dim=True))
        else:
            for i, d in enumerate(devices):
                pct = f"{d.percent_text}%"
                if d.charging:
                    pct += " · 充电中"
                values = [d.name, d.type_label, pct, d.source or "-"]
                for j, v in enumerate(values):
                    self.dev_table.setItem(i, j, _cell(v, right=(j == 2)))

        failed = (self._result or {}).get("failed") or []
        if failed:
            self.fail_label.show()
            self.fail_table.show()
            self.fail_label.setText(f"没能读取 · {len(failed)}")
            self.fail_table.setRowCount(len(failed))
            for i, row in enumerate(failed):
                self.fail_table.setItem(i, 0, _cell(row.get("name") or "-"))
                self.fail_table.setItem(i, 1, _cell(row.get("vid_pid") or "-", dim=True))
                self.fail_table.setItem(i, 2, _cell(row.get("reason") or "-", dim=True))
            self.fail_table.resizeRowsToContents()
        else:
            self.fail_label.hide()
            self.fail_table.hide()

    # ---------------- 导出 ----------------
    def _export(self) -> None:
        """导出前同样跑一遍自动诊断：报告里就有失败原因和原始帧。"""
        self._debug = []
        self._run("report")

    def _write_report(self, result: dict) -> None:
        import platform
        from datetime import datetime

        from config import config_dir

        devices = result.get("devices") or []
        eps = result.get("endpoints_list") or []
        lines: list[str] = [
            "外设电量 · 诊断报告",
            "=" * 46,
            f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
            f"程序版本：{APP_VERSION}",
            f"系统版本：{platform.platform()}",
            f"Python：{platform.python_version()} ({platform.architecture()[0]})",
            "",
            f"【一、识别到的外设】共 {len(devices)} 台",
        ]
        if devices:
            for i, d in enumerate(devices, 1):
                lines.append(
                    f"{i}. {d.name} | {d.type_label} | {d.percent_text}% "
                    f"| 充电={'是' if d.charging else '否'} | 通道={d.source or '-'} "
                    f"| 连接={d.transport or '-'} | VID:PID={d.vid_pid or '-'} "
                    f"| 状态={(d.raw or {}).get('state', '-')}")
        else:
            lines.append("（无）")

        failed = result.get("failed") or []
        lines += ["", f"【二、没读到的接收器】共 {len(failed)} 台"]
        if failed:
            for row in failed:
                lines.append(f"{row.get('vid_pid') or '-'} | {row.get('name') or '-'} "
                             f"| {row.get('reason') or '-'}")
        else:
            lines.append("（无）")

        lines += ["", "【三、XInput 槽位】手柄走 XInput 时只有四档，这里看原始值"]
        lines.extend(result.get("xinput") or ["（未采集）"])

        lines += ["", f"【四、HID 端点】共 {len(eps)} 个（★ = 厂商协议通道，电量候选）"]
        for ep in eps:
            lines.append(
                f"{ep['vendor_id']:04X}:{ep['product_id']:04X} | "
                f"{describe_vendor(ep['vendor_id'])} | "
                f"{ep['manufacturer'] or '-'} | {ep['product'] or '-'} | "
                f"页=0x{(ep['usage_page'] or 0):04X} 用法=0x{(ep['usage'] or 0):04X} | "
                f"{'★ ' if ep.get('recommend') else ''}{ep.get('role') or '-'} | "
                f"接口={ep['interface']}")

        debug = result.get("logs") or self._debug
        samples = result.get("samples") or []
        lines += ["", "【五、厂商端点被动采样】每个候选端点听 2 秒，原样记录上报帧"]
        lines.extend(samples or ["（没有可采样的厂商端点）"])

        lines += ["", f"【六、扫描日志】共 {len(debug)} 行"]
        lines.extend(debug or ["（无）"])
        lines += ["", "=" * 46, "请把本文件整份发回，内容越多越好，不要删减。"]

        folder = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        if not folder:
            folder = str(config_dir())
        path = Path(folder) / f"外设电量诊断_{datetime.now():%Y%m%d_%H%M%S}.txt"
        try:
            path.write_text("\n".join(lines), encoding="utf-8-sig")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"写文件失败：{exc}")
            self.status.setText("导出失败")
            return

        self.status.setText(f"已导出：{path}")
        QMessageBox.information(
            self, "诊断报告已导出",
            f"已保存到：\n{path}\n\n把这个 txt 整份发回来即可定位问题。")

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        super().closeEvent(event)
