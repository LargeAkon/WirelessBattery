# -*- coding: utf-8 -*-
"""添加设备：选接收器 → 选品牌型号（可搜索）→ 试读 → 添加。

为什么要这个窗口：自动诊断是「我替你猜」，猜不到的时候（私有帧、同 ID 多品牌）
需要人给一个提示。原来的做法是让人复制端点文本，那是给开发者用的；
这里改成从协议库里选型号 —— 用户只需要知道自己的设备叫什么。

界面就是四步，没有说明段落：
    上面：点一台接收器
    中间：选型号（或直接「自动探测」）
    下面：试读 → 添加
试读通过才会写盘：写的是配置目录里的外置协议，下次启动直接读，不用再点诊断。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

import autodiag
import profiles
from ui.rows import PickRow, clear_layout, scroll_list, setup_dialog


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


class AddDeviceWindow(QDialog):
    added = Signal()

    def __init__(self, config, known: set[str] | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self._known = known or set()
        self._receivers: list[dict] = []
        self._rows: list[PickRow] = []
        self._index = -1
        self._worker: _Worker | None = None
        self._result: dict | None = None
        self._tried: set[str] = set()

        self.setWindowTitle("添加设备")
        setup_dialog(self, (480, 440))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(11)

        title = QLabel("选择要添加的设备")
        title.setObjectName("DiagTitle")
        root.addWidget(title)

        # ---------- 接收器列表（一行一台，点一下选中） ----------
        self.scroll, self.list_lay = scroll_list(spacing=4)
        root.addWidget(self.scroll, 1)

        # ---------- 型号 ----------
        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setFixedHeight(30)
        self._fill_combo()
        # 可搜索下拉的两个手感问题：
        # 1) 框里已经有一行"自动判断…"，直接打字是往后追加，搜不出东西 ——
        #    聚焦时全选，敲第一个键就整行替换，不用先手动删字；
        # 2) 用户点输入框是想展开列表，不是想编辑那行字 —— 点一下直接弹列表。
        self.combo.lineEdit().installEventFilter(self)
        self.combo.lineEdit().textEdited.connect(self._on_combo_typed)
        row.addWidget(self.combo, 1)

        self.probe_btn = QPushButton("自动探测")
        self.probe_btn.setObjectName("Ghost")
        self.probe_btn.setCursor(Qt.PointingHandCursor)
        self.probe_btn.setFixedHeight(30)
        self.probe_btn.clicked.connect(self._probe)
        row.addWidget(self.probe_btn)
        root.addLayout(row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("名称（可不填）")
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
        self.add_btn.setFixedHeight(32)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        bottom.addWidget(self.add_btn)
        root.addLayout(bottom)

        self.reload()

    # ---------------- 数据 ----------------
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        # 窗口关闭 / 解释器退出时，Qt 仍可能把排队的事件送到这里，
        # 此时输入框的 C++ 对象已经销毁，访问它就抛 RuntimeError。
        try:
            line = self.combo.lineEdit()
            if obj is line:
                if ev.type() == QEvent.FocusIn:
                    # 全选要在下一个事件循环做：焦点事件本身还会重设光标位置
                    QTimer.singleShot(0, self._select_all)
                elif ev.type() == QEvent.MouseButtonPress:
                    QTimer.singleShot(0, self._popup)
        except RuntimeError:
            return False
        return super().eventFilter(obj, ev)

    def _select_all(self) -> None:
        try:
            self.combo.lineEdit().selectAll()
        except RuntimeError:
            pass

    def _popup(self) -> None:
        try:
            self.combo.showPopup()
        except RuntimeError:
            pass

    def _on_combo_typed(self, _text: str) -> None:
        # 用户开始打字了：完整列表让位给搜索补全，两个浮层别叠在一起
        if self.combo.view().isVisible():
            self.combo.hidePopup()

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

    def _clear_rows(self) -> None:
        clear_layout(self.list_lay)
        self._rows = []

    def reload(self) -> None:
        self._receivers = autodiag.receivers(self._known)
        self._index = -1
        self._clear_rows()

        if not self._receivers:
            empty = QLabel("没有需要添加的设备")
            empty.setObjectName("DiagEmpty")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.addWidget(empty)
            self.list_lay.addStretch(1)
            self.tip.setText("已连接的无线设备都能读到电量")
            self.add_btn.setEnabled(False)
            return

        for index, receiver in enumerate(self._receivers):
            row = PickRow(receiver["name"], receiver["vid_pid"], receiver.get("kind") or "")
            row.picked.connect(lambda i=index: self.pick(i))
            self.list_lay.addWidget(row)
            self._rows.append(row)
        self.list_lay.addStretch(1)
        self.pick(0)

    def pick(self, index: int) -> None:
        if not (0 <= index < len(self._receivers)):
            return
        self._index = index
        for i, row in enumerate(self._rows):
            row.set_picked(i == index)
        self._tried.clear()
        # 换了台接收器，上一台的试读结果必须作废。留着它会带来两个错：
        # 「添加设备」仍然可点（结果还是 ok），点下去写的是上一台的型号；
        # 名称框里也还挂着上一台的名字。
        self._result = None
        self.add_btn.setEnabled(False)
        self.name_edit.clear()
        self.tip.setText("")
        # 自动探测从零开始，按钮也放开
        self.probe_btn.setEnabled(True)
        self.probe_btn.setToolTip("")
        receiver = self._receivers[index]
        guesses = receiver.get("guesses") or []
        if guesses:
            combo_index = self.combo.findData(guesses[0])
            if combo_index >= 0:
                self.combo.setCurrentIndex(combo_index)
                return
        self.combo.setCurrentIndex(0)

    def _receiver(self) -> dict | None:
        if 0 <= self._index < len(self._receivers):
            return self._receivers[self._index]
        return None

    # ---------------- 试读 / 探测 ----------------
    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.test_btn.setEnabled(not busy)
        self.probe_btn.setEnabled(not busy)
        self.scroll.setEnabled(not busy)
        self.combo.setEnabled(not busy)
        if busy:
            self.add_btn.setEnabled(False)
            self.tip.setText(text or "正在读取…")
        else:
            # 只有试读通了才允许添加：没读到电量就写盘，加进去也是一台"读不到"
            self.add_btn.setEnabled(bool((self._result or {}).get("ok")))

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
        worker = _Worker(job, receiver, profile_id,
                         self._tried if job == "probe" else None, self)
        worker.progress.connect(lambda text: self.tip.setText(text))
        worker.done.connect(self._on_done)
        # 线程真正退完再松手：done 到达时 isRunning() 仍可能为 True，
        # 这时候清引用会让"再来一次"的按钮判定失真。
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._worker = worker
        worker.start()

    def _on_worker_finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_done(self, result: dict) -> None:
        self._result = result
        self._set_busy(False)
        self.tip.setText(result.get("text") or "")
        for pid in result.get("tried_ids") or []:
            self._tried.add(pid)
        # 这台接收器能试的都试完了：再点「自动探测」只会空转（以前就是
        # 点一次"试了 0 条"、再点一次还是"试了 0 条"），直接停掉并指路
        if result.get("job") == "probe" and not result.get("remaining"):
            self.probe_btn.setEnabled(False)
            self.probe_btn.setToolTip("这台接收器上可试的协议都试过了，请从型号里选")
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

        self.tip.setText(f"已添加 · {label}")
        self.added.emit()
        # 加完就把它从"待添加"里去掉，列表不该还挂着刚加过的那台
        self._known.add(receiver["vid_pid"].upper())
        self.reload()
        # reload 会重选第一台并清空提示，这里把"已添加"补回去
        self.tip.setText(f"已添加 · {label}")

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)
