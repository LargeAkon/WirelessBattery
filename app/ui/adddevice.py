# -*- coding: utf-8 -*-
"""添加设备：接收器列表 → 选品牌型号 → 试读 → 添加。

为什么要这个窗口：自动诊断是「我替你猜」，猜不到的时候（私有帧、同 ID 多品牌）
需要人给一个提示。原来的做法是让人复制端点文本，那是给开发者用的；
这里改成从协议库里选型号 —— 用户只需要知道自己的设备叫什么。

界面上只有四步，没有说明段落：
    左边选接收器 → 右边选型号（可搜索）→ 试读 → 添加
试读通过才会写盘：写的是配置目录里的外置协议，下次启动直接读，不用再点诊断。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

import autodiag
import profiles
import theme
from PySide6.QtGui import QPalette


class _Worker(QThread):
    """试读 / 自动探测都要发帧等应答，必须离开 UI 线程。"""

    done = Signal(dict)
    progress = Signal(str)

    def __init__(self, job: str, receiver: dict, profile_id: str = "",
                 skip: set | None = None, parent=None):
        super().__init__(parent)
        self.job = job
        self.receiver = receiver
        self.profile_id = profile_id
        self.skip = skip or set()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            if self.job == "probe":
                result = autodiag.auto_probe(
                    self.receiver,
                    progress=lambda text, _pct: self.progress.emit(text),
                    stop=self._stop,
                    skip=self.skip,
                )
            else:
                result = autodiag.detect(self.receiver, self.profile_id)
        except Exception as exc:
            result = {"ok": False, "text": f"出错了：{type(exc).__name__}: {exc}"}
        result["job"] = self.job
        self.done.emit(result)


def _style_table(t: QTableWidget) -> None:
    pal = t.palette()
    soft = theme.color(theme.BG_SOFT)
    text = theme.color(theme.TEXT)
    for role, color in ((QPalette.Base, soft), (QPalette.Window, soft),
                        (QPalette.Text, text), (QPalette.WindowText, text),
                        (QPalette.Highlight, theme.color(theme.BG_ROW_HOVER)),
                        (QPalette.HighlightedText, text)):
        pal.setColor(role, color)
    t.setPalette(pal)
    t.viewport().setPalette(pal)
    t.horizontalHeader().setPalette(pal)


class AddDeviceWindow(QDialog):
    added = Signal()

    def __init__(self, config, known: set[str] | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self._known = known or set()
        self._receivers: list[dict] = []
        self._worker: _Worker | None = None
        self._result: dict | None = None
        self._tried: set[str] = set()

        self.setWindowTitle("添加设备")
        self.setObjectName("DiagRoot")
        self.setStyleSheet(theme.qss())
        self.setMinimumSize(560, 460)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["接收器", "编号"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QTableWidget.NoFrame)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 92)
        _style_table(self.table)
        self.table.itemSelectionChanged.connect(self._on_receiver)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setFixedHeight(30)
        self._fill_combo()
        row.addWidget(self.combo, 1)

        self.probe_btn = QPushButton("自动探测")
        self.probe_btn.setObjectName("Ghost")
        self.probe_btn.setCursor(Qt.PointingHandCursor)
        self.probe_btn.setFixedHeight(30)
        self.probe_btn.clicked.connect(self._probe)
        row.addWidget(self.probe_btn)
        root.addLayout(row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("设备名称（可不填，默认用型号名）")
        self.name_edit.setFixedHeight(30)
        root.addWidget(self.name_edit)

        self.tip = QLabel("")
        self.tip.setObjectName("DiagStatus")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.test_btn = QPushButton("试读")
        self.test_btn.setObjectName("Ghost")
        self.test_btn.setCursor(Qt.PointingHandCursor)
        self.test_btn.setFixedHeight(30)
        self.test_btn.clicked.connect(self._test)
        bottom.addWidget(self.test_btn)
        bottom.addStretch(1)
        self.add_btn = QPushButton("添加设备")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFixedHeight(30)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        bottom.addWidget(self.add_btn)
        root.addLayout(bottom)

        self.reload()

    # ---------------- 数据 ----------------
    def _fill_combo(self) -> None:
        self.combo.clear()
        self.combo.addItem("自动判断（按 ID 匹配）", "")
        groups: dict[str, list[dict]] = {}
        for item in profiles.choices()[1:]:
            groups.setdefault(item["vendor"], []).append(item)
        for vendor in sorted(groups):
            self.combo.insertSeparator(self.combo.count())
            for item in groups[vendor]:
                # 品牌写进条目本身，搜索「凌豹」「VGN」都能命中
                self.combo.addItem(f"{vendor} · {item['label']}", item["id"])
        completer = QCompleter([self.combo.itemText(i) for i in range(self.combo.count())],
                               self.combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.combo.setCompleter(completer)

    def reload(self) -> None:
        self._receivers = autodiag.receivers(self._known)
        self.table.setRowCount(max(1, len(self._receivers)))
        if not self._receivers:
            self.table.setItem(0, 0, QTableWidgetItem("没有需要添加的接收器"))
            self.table.setItem(0, 1, QTableWidgetItem(""))
            self.tip.setText("已连接的无线设备都能读到电量")
            self.add_btn.setEnabled(False)
            return
        for i, item in enumerate(self._receivers):
            self.table.setItem(i, 0, QTableWidgetItem(item["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(item["vid_pid"]))
        self.table.selectRow(0)

    def _receiver(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._receivers):
            return self._receivers[index]
        return None

    def _on_receiver(self) -> None:
        receiver = self._receiver()
        if receiver is None:
            return
        self._tried.clear()
        guesses = receiver.get("guesses") or []
        if guesses:
            index = self.combo.findData(guesses[0])
            if index >= 0:
                self.combo.setCurrentIndex(index)
                return
        self.combo.setCurrentIndex(0)

    # ---------------- 试读 / 探测 ----------------
    def _set_busy(self, busy: bool, text: str = "") -> None:
        for btn in (self.test_btn, self.probe_btn, self.add_btn):
            btn.setEnabled(not busy)
        if busy:
            self.tip.setText(text or "正在读取…")
        self.table.setEnabled(not busy)

    def _test(self) -> None:
        receiver = self._receiver()
        if receiver is None:
            return
        self._start("test", receiver, self.combo.currentData() or "")

    def _probe(self) -> None:
        receiver = self._receiver()
        if receiver is None:
            return
        self._start("probe", receiver)

    def _start(self, job: str, receiver: dict, profile_id: str = "") -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._result = None
        self.add_btn.setEnabled(False)
        self._set_busy(True, "正在探测…" if job == "probe" else "正在读取…")
        self._worker = _Worker(job, receiver, profile_id,
                               self._tried if job == "probe" else None, self)
        self._worker.progress.connect(lambda text: self.tip.setText(text))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, result: dict) -> None:
        self._set_busy(False)
        self._result = result
        self.tip.setText(result.get("text") or "")
        for pid in result.get("tried_ids") or []:
            self._tried.add(pid)
        profile = result.get("profile")
        if result.get("ok") and profile is not None:
            index = self.combo.findData(profile["id"])
            if index >= 0:
                self.combo.setCurrentIndex(index)
            if not self.name_edit.text().strip():
                self.name_edit.setText(profile["label"])
            self.add_btn.setEnabled(True)

    # ---------------- 添加 ----------------
    def _add(self) -> None:
        receiver = self._receiver()
        result = self._result or {}
        profile = result.get("profile")
        if receiver is None or profile is None or not result.get("ok"):
            return

        eps = autodiag.vendor_endpoints(receiver.get("endpoints") or [])
        if not eps:
            QMessageBox.warning(self, "添加失败", "这只接收器没有厂商协议端点")
            return
        usage_page = result.get("usage_page") or eps[0].get("usage_page") or 0
        usage = result.get("usage")
        if usage is None:
            usage = eps[0].get("usage") or 0

        name = self.name_edit.text().strip()
        try:
            key, label = autodiag.remember(
                receiver, profile, usage_page, usage, name=name,
                kind=receiver.get("kind") or "")
        except Exception as exc:
            QMessageBox.warning(self, "添加失败", f"写配置文件失败：{exc}")
            return

        # 名字自己填过就记下来，下轮扫描按 key 覆盖显示名
        if name:
            try:
                self.config.set_override(key, receiver.get("kind") or None, name)
            except Exception:
                pass

        self.tip.setText(f"已添加 · {label}（{result.get('text') or ''}）")
        self.added.emit()
        # 加完就把它从"待添加"里去掉，列表不该还挂着刚加过的那台
        self._known.add(receiver["vid_pid"].upper())
        self._receivers = []
        self.reload()

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)
