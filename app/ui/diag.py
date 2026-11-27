# -*- coding: utf-8 -*-
"""设备诊断：一个按钮，自动把能读到的设备都找出来。

旧版是一张端点表 + 复制 + 粘贴 + 识别，要求用户先看懂"页面 0xFF00、
用法 0x0002"才知道该复制哪一行 —— 实际反馈是绝大多数人卡在这一步。
1.5.28 改成一条流水线，但页面上仍是两张表 + 两组小标题 + 一堆说明。

现在只留三块，从上到下就是一条视线：

    [设备诊断]                                    [添加设备]
    [            自动查找设备            ]
      ● VGN VXE75 V2            85%
      ● 无线键盘                 45%
      ○ 2.4G Receiver           读不到
    识别到 2 台设备 · 另有 1 台读不到            [导出报告]

读不到的行压暗、字号也小一号，扫一眼就知道哪台成了。
"""
from __future__ import annotations

import platform
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import autodiag
import theme
from config import APP_VERSION, Config, config_dir
from model import Device
from providers import raw_hid
from ui.adddevice import AddDeviceWindow
from ui.rows import Row, clear_layout, scroll_list, setup_dialog
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
        except Exception as exc:
            result = {
                "error": f"{type(exc).__name__}: {exc}",
                "devices": [], "failed": [],
                "endpoints": 0, "seconds": 0.0, "logs": [],
            }
        result["mode"] = self.mode
        self.done.emit(result)


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
        setup_dialog(self, (430, 420))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(13)

        # ---------- 标题行：名字 + 一个次要动作 ----------
        head = QHBoxLayout()
        head.setSpacing(8)
        self.head = QLabel("设备诊断")
        self.head.setObjectName("DiagTitle")
        head.addWidget(self.head, 0, Qt.AlignVCenter)
        head.addStretch(1)
        self.add_btn = QPushButton("添加设备")
        self.add_btn.setObjectName("Link")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFixedHeight(24)
        self.add_btn.clicked.connect(self._open_add)
        head.addWidget(self.add_btn, 0, Qt.AlignVCenter)
        root.addLayout(head)

        # ---------- 唯一的主要动作 ----------
        self.btn = QPushButton("自动查找设备")
        self.btn.setObjectName("Primary")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(40)
        self.btn.clicked.connect(self._start)
        root.addWidget(self.btn)

        self.bar = QProgressBar()
        self.bar.setObjectName("DiagBar")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.hide()
        root.addWidget(self.bar)

        # ---------- 中间：空态 / 结果列表 / 识别中 ----------
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        page_empty = QWidget()
        empty_lay = QVBoxLayout(page_empty)
        empty_lay.setContentsMargins(0, 0, 0, 0)
        empty_lay.addStretch(1)
        self.empty = QLabel("")
        self.empty.setObjectName("DiagEmpty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        empty_lay.addWidget(self.empty)
        empty_lay.addStretch(1)
        self.stack.addWidget(page_empty)
        self._page_empty = page_empty

        self.scroll, self.list_lay = scroll_list(spacing=2)
        self.stack.addWidget(self.scroll)
        self._page_list = self.scroll

        page_busy = QWidget()
        busy_lay = QVBoxLayout(page_busy)
        busy_lay.setContentsMargins(0, 0, 0, 0)
        busy_lay.setSpacing(6)
        busy_lay.addStretch(1)
        self.step_title = QLabel("正在识别…")
        self.step_title.setObjectName("DiagTitle")
        self.step_title.setAlignment(Qt.AlignCenter)
        busy_lay.addWidget(self.step_title)
        self.step = QLabel("")
        self.step.setObjectName("DiagEmpty")
        self.step.setAlignment(Qt.AlignCenter)
        self.step.setWordWrap(True)
        busy_lay.addWidget(self.step)
        busy_lay.addStretch(1)
        self.stack.addWidget(page_busy)
        self._page_busy = page_busy

        # ---------- 底部：一句话结论 + 导出 ----------
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.status = QLabel("")
        self.status.setObjectName("DiagStatus")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.export_btn = QPushButton("导出报告")
        self.export_btn.setObjectName("Link")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setFixedHeight(24)
        self.export_btn.clicked.connect(self._export)
        foot.addWidget(self.export_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(foot)

        self.resize(460, 520)
        self.update_devices([], [])

    # ---------------- 状态切换 ----------------
    @property
    def busy(self) -> bool:
        # 用显式标志而不是 QThread.isRunning()：done 信号可能在线程真正
        # 结束前一瞬到达，那时 isRunning() 还是 True，按钮会被误判成"忙"。
        return self._running

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.btn.setEnabled(not busy)
        self.btn.setText("正在识别…" if busy else "自动查找设备")
        self.add_btn.setEnabled(not busy)
        self.export_btn.setEnabled(not busy)
        self.bar.setVisible(busy)
        if busy:
            self.bar.setValue(0)
            self.step.setText(text or "")
            self.stack.setCurrentWidget(self._page_busy)
        else:
            self.bar.setValue(100)

    def _on_progress(self, text: str, pct: int) -> None:
        self.bar.setValue(max(0, min(100, int(pct))))
        self.step.setText(text)
        self.status.setText("识别中，请勿关闭…")

    # ---------------- 主题 ----------------
    def apply_theme(self) -> None:
        """主题切换后整体重刷。

        窗口已经关掉时不能重建列表。重建会把每一行先摘成独立窗口，
        屏幕上就是诊断页闪一下又自己关掉。图标磁贴和电量是自己画的，
        换完样式表再 update 就会跟着变色。
        """
        shown = self.isVisible()
        self.setStyleSheet(theme.qss())
        self.update()
        for child in self.findChildren(QWidget):
            child.update()
        if not shown:
            self.hide()

    # ---------------- 运行 ----------------
    def _start(self) -> None:
        self._run("diag")

    def _run(self, mode: str) -> None:
        if self.busy:
            return
        self._running = True
        self._set_busy(True)
        self.status.setText("识别中，请勿关闭…")
        self._worker = AutoDiagWorker(self.config, mode=mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        # 线程真正结束后再松手 + 释放。done 信号到达时线程可能还没退完，
        # 提前把引用丢掉会让 QThread 在运行中被回收（Qt 会直接崩）。
        # 把 worker 自己传进回调：万一下一轮已经起来了，旧线程收尾时
        # 不能把新线程的引用一起清掉。
        worker = self._worker
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_worker_finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_done(self, result: dict) -> None:
        self._running = False
        self._set_busy(False)
        self._result = result

        if result.get("error"):
            self.status.setText(f"诊断失败：{result['error']}")
            self._render()
            return

        debug = result.get("logs") or []
        if debug:
            self._debug = debug
        self.update_devices(result.get("devices") or [], [])

        if result.get("mode") == "report":
            self._write_report(result)
            return
        if result.get("mode") == "refresh":
            # 添加设备后只刷新列表，失败原因还是上一轮的结论。
            # 这里必须给一句新状态 —— 否则底部会一直停在
            # "识别中，请勿关闭…"，看起来像卡住了。
            count = len(result.get("devices") or [])
            self.status.setText(f"已读到 {count} 台设备" if count else "当前没有读到电量的设备")
            self.rule_changed.emit()
            return

        self.status.setText(autodiag.summary(result))
        # 诊断结果要立刻反映到卡片上（类型纠偏、已添加协议），
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

    # ---------------- 列表 ----------------
    def _render(self) -> None:
        clear_layout(self.list_lay)
        devices = self._devices
        failed = (self._result or {}).get("failed") or []

        for device in devices:
            source = device.source or device.type_label
            sub = f"{source} · 充电中" if device.charging else source
            row = Row(device.name, sub, kind=device.kind)
            row.show_percent(device.percent_text)
            self.list_lay.addWidget(row)

        for item in failed:
            row = Row(item.get("name") or "无线接收器",
                      item.get("reason") or "", dim=True)
            row.show_state("读不到")
            self.list_lay.addWidget(row)

        self.list_lay.addStretch(1)

        if devices or failed:
            self.stack.setCurrentWidget(self._page_list)
            return
        if self._result:
            self.empty.setText("没有找到能读电量的设备\n点右上角「添加设备」手动指定型号")
        else:
            self.empty.setText("点上面的按钮，自动找出能读电量的设备")
        self.stack.setCurrentWidget(self._page_empty)

    def update_devices(self, devices: list[Device], debug: list[str]) -> None:
        if self.busy:
            # 自动诊断跑着的时候，主窗口的定时刷新不要来抢列表
            return
        if debug:
            self._debug = list(debug)
        self._devices = sorted(devices or [], key=lambda d: d.sort_key())
        self._render()

    # ---------------- 导出 ----------------
    def _export(self) -> None:
        """导出前同样跑一遍自动诊断：报告里就有失败原因和原始帧。"""
        self._debug = []
        self._run("report")

    def _write_report(self, result: dict) -> None:
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

        lines += ["", f"【三、HID 端点】共 {len(eps)} 个（★ = 厂商协议通道，电量候选）"]
        for ep in eps:
            lines.append(
                f"{ep['vendor_id']:04X}:{ep['product_id']:04X} | "
                f"{describe_vendor(ep['vendor_id'])} | "
                f"{ep['manufacturer'] or '-'} | {ep['product'] or '-'} | "
                f"页=0x{(ep['usage_page'] or 0):04X} 用法=0x{(ep['usage'] or 0):04X} | "
                f"{'★ ' if ep.get('recommend') else ''}{ep.get('role') or '-'} | "
                f"接口={ep['interface']}")

        debug = result.get("logs") or self._debug
        lines += ["", f"【四、扫描日志】共 {len(debug)} 行"]
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
