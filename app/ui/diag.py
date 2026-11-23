# -*- coding: utf-8 -*-
"""设备诊断：看清每一条 HID 通道，并把任意新设备接进来。

流程（做过简化：原来要"选端点 → 嗅探 → 手填名称类型 → 存规则"四步）：
    1. 上方看当前已经识别到的设备；
    2. 中间端点表，找到有用的那一行，点右侧「复制」；
    3. 下方粘贴 → 点「识别」，程序自动定位端点、自动读电量、自动存规则。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths, QThread, Signal
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import theme
from config import APP_VERSION, Config
from model import Device
from providers import raw_hid
from recognize import endpoint_text, recognize
from vendors import describe as describe_vendor


class RecognizeWorker(QThread):
    """识别流程里有 HID 握手和 3 秒被动监听，必须离开 UI 线程。"""

    done = Signal(dict)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text

    def run(self) -> None:
        try:
            result = recognize(self.text)
        except Exception as exc:
            result = {"ok": False, "message": f"识别失败：{type(exc).__name__}: {exc}"}
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


def _cell(value: str, dim: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setForeground(theme.color(theme.TEXT_DIM if dim else theme.TEXT))
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
    t.horizontalHeader().setStretchLastSection(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    _style_table(t)
    return t


class DiagWindow(QWidget):
    rule_changed = Signal()

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self.endpoints: list[dict] = []
        self._worker: RecognizeWorker | None = None
        self._devices: list[Device] = []
        self._debug: list[str] = []

        self.setWindowTitle("设备诊断与规则")
        self.setMinimumSize(780, 560)
        self.setObjectName("DiagRoot")
        self.setStyleSheet(theme.qss())
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        # 内容放进滚动区：窗口可以矮，内容永远不被压缩
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
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        self.head = QLabel("设备诊断与规则")
        self.head.setObjectName("DiagTitle")
        root.addWidget(self.head)
        self.tip = QLabel("中间表格只复制标 ★ 的那一行，粘到下面点识别，程序自己认端点、自己读电量。")
        self.tip.setObjectName("DiagTip")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        # ---------- 一、已识别设备（最上方） ----------
        dev_box = QGroupBox("当前识别到的外设")
        dev_lay = QVBoxLayout(dev_box)
        self.dev_table = _table(["设备", "类型", "电量", "来源通道", "连接"])
        self.dev_table.setFixedHeight(120)
        dev_lay.addWidget(self.dev_table)
        root.addWidget(dev_box)

        # ---------- 二、HID 端点（中间，右侧复制按钮） ----------
        ep_box = QGroupBox("HID 端点")
        ep_lay = QVBoxLayout(ep_box)
        self.ep_table = _table(["厂商:产品", "设备名", "页面/用法", "用途", "接口", "复制"])
        self.ep_table.setFixedHeight(210)
        self.ep_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.ep_table.setColumnWidth(5, 64)
        self.ep_table.itemSelectionChanged.connect(self._on_endpoint_pick)
        ep_lay.addWidget(self.ep_table)
        self.ep_tip = QLabel(
            "★ 是厂商协议通道，电量只从这里出来；鼠标 / 键盘 / 多媒体那几行只是输入报文。"
            "整张表都没有 ★ 时，复制「厂商协议」那几行逐条试。")
        self.ep_tip.setObjectName("DiagTip")
        self.ep_tip.setWordWrap(True)
        ep_lay.addWidget(self.ep_tip)
        root.addWidget(ep_box)

        # ---------- 三、粘贴识别 ----------
        rec_box = QGroupBox("识别并添加设备")
        rec_lay = QVBoxLayout(rec_box)
        rec_row = QHBoxLayout()
        self.paste_edit = QLineEdit()
        self.paste_edit.setPlaceholderText(
            "把上面「复制」得到的端点信息粘贴到这里，例如 046D:C54D | USB Receiver | 页面=0xFF00 用法=0x0002 …")
        self.paste_edit.returnPressed.connect(self._recognize)
        rec_row.addWidget(self.paste_edit, 1)
        self.rec_btn = QPushButton("识别")
        self.rec_btn.setObjectName("Ghost")
        self.rec_btn.setFixedHeight(30)
        self.rec_btn.setFixedWidth(78)
        self.rec_btn.clicked.connect(self._recognize)
        rec_row.addWidget(self.rec_btn)
        rec_lay.addLayout(rec_row)
        self.rec_result = QLabel("")
        self.rec_result.setObjectName("DiagStatus")
        self.rec_result.setWordWrap(True)
        rec_lay.addWidget(self.rec_result)
        root.addWidget(rec_box)

        # ---------- 四、导出 ----------
        export_row = QHBoxLayout()
        self.export_btn = QPushButton("导出诊断报告")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self._export_report)
        export_row.addWidget(self.export_btn)
        self.export_tip = QLabel("别人那边读不到设备时，让他导出这个 txt 发回来")
        self.export_tip.setObjectName("DiagTip")
        export_row.addWidget(self.export_tip, 1)
        root.addLayout(export_row)

        self.status = QLabel("")
        self.status.setObjectName("DiagStatus")
        root.addWidget(self.status)

        self.refresh_endpoints()

        hint = content.sizeHint()
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(
            max(780, hint.width()),
            min(hint.height(), max(560, int(avail.height() * 0.88))),
        )

    # ---------------- 主题 ----------------
    def apply_theme(self) -> None:
        """主题切换后重建样式：诊断页的表格吃 palette，光换 qss 不够。"""
        self.setStyleSheet(theme.qss())
        for table in (self.dev_table, self.ep_table):
            _style_table(table)
            for row in range(table.rowCount()):
                for col in range(5):
                    item = table.item(row, col)
                    if item is not None and not item.font().bold():
                        item.setForeground(theme.color(theme.TEXT))
        self.update()

    # ---------------- 数据 ----------------
    def refresh_endpoints(self) -> None:
        self.endpoints = raw_hid.describe_endpoints()
        self.ep_table.setRowCount(len(self.endpoints))
        first_recommend = -1
        for i, ep in enumerate(self.endpoints):
            values = [
                f"{ep['vendor_id']:04X}:{ep['product_id']:04X}",
                ep.get("product") or "-",
                f"0x{(ep['usage_page'] or 0):04X} / 0x{(ep['usage'] or 0):04X}",
                ep.get("role") or "-",
                "-" if (ep["interface"] is None or ep["interface"] < 0)
                else str(ep["interface"]),
            ]
            for j, v in enumerate(values):
                item = _cell(v)
                if ep.get("recommend"):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(theme.color(theme.ACCENT))
                self.ep_table.setItem(i, j, item)

            btn = QPushButton("复制")
            btn.setObjectName("Ghost")
            btn.setFixedHeight(24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, e=ep: self._copy_endpoint(e))
            self.ep_table.setCellWidget(i, 5, btn)

            if ep.get("recommend") and first_recommend < 0:
                first_recommend = i

        self.status.setText(f"共 {len(self.endpoints)} 个 HID 端点")
        if first_recommend >= 0:
            self.ep_table.selectRow(first_recommend)
            self.ep_table.scrollToItem(self.ep_table.item(first_recommend, 0))

    def _on_endpoint_pick(self) -> None:
        ep = self._selected_endpoint()
        if not ep:
            return
        if (ep.get("usage_page") or 0) < 0xFF00:
            self.ep_tip.setText(
                f"当前选中的是「{ep.get('role')}」端点，它本身只上报输入动作；"
                "识别时程序仍会按厂商再试一次，失败了就改复制标 ★ 的那一行。")
        else:
            self.ep_tip.setText(
                "★ 是厂商协议通道，电量只从这里出来；鼠标 / 键盘 / 多媒体那几行只是输入报文。"
                "整张表都没有 ★ 时，复制「厂商协议」那几行逐条试。")

    def _selected_endpoint(self) -> dict | None:
        row = self.ep_table.currentRow()
        if row < 0 or row >= len(self.endpoints):
            return None
        return self.endpoints[row]

    def update_devices(self, devices: list[Device], debug: list[str]) -> None:
        self._devices = list(devices or [])
        if debug:
            self._debug = list(debug)
        self.dev_table.setRowCount(len(devices))
        for i, d in enumerate(devices):
            values = [d.name, d.type_label, f"{d.percent_text}%",
                      d.source or "-", d.transport or "-"]
            for j, v in enumerate(values):
                self.dev_table.setItem(i, j, _cell(v))
        if not devices:
            self.dev_table.setRowCount(1)
            self.dev_table.setItem(0, 0, _cell("（未识别到带电量信息的外设）", dim=True))

    # ---------------- 复制 ----------------
    def _copy_endpoint(self, ep: dict) -> None:
        text = endpoint_text(ep)
        QGuiApplication.clipboard().setText(text)
        # 顺手填进下面的输入框：用户连粘贴都不用做，直接点识别
        self.paste_edit.setText(text)
        self.paste_edit.setCursorPosition(0)
        self.rec_result.setText(f"已复制并填入：{ep.get('product') or '-'} "
                                f"{ep.get('role') or ''}，点「识别」即可。")
        self.paste_edit.setFocus()
        self.paste_edit.selectAll()

    # ---------------- 识别 ----------------
    def _recognize(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        text = self.paste_edit.text().strip()
        if not text:
            self.rec_result.setText("先复制一行端点信息粘进来。")
            return
        self.rec_btn.setEnabled(False)
        self.rec_btn.setText("识别中…")
        self.rec_result.setText("正在定位端点并读取电量…")
        self._worker = RecognizeWorker(text)
        self._worker.done.connect(self._on_recognized)
        self._worker.start()

    def _on_recognized(self, result: dict) -> None:
        self.rec_btn.setEnabled(True)
        self.rec_btn.setText("识别")
        debug = result.get("debug") or []
        if debug:
            self._debug.extend(debug)

        if not result.get("ok"):
            self.rec_result.setText(result.get("message") or "识别失败。")
            self.status.setText("识别失败")
            return

        device: Device = result["device"]
        rule = result.get("rule")
        if rule:
            self._save_rule(rule)

        # 立刻把它显示到上方表格，不用等下一轮扫描
        merged = [d for d in self._devices if d.key != device.key] + [device]
        self.update_devices(merged, [])

        extra = ""
        if not rule and (device.source or "").startswith(("HID++", "Evision")):
            extra = "（该品牌有内置通道，无需规则，以后刷新自动读取）"
        self.rec_result.setText(f"{result.get('message') or '已识别'}{extra}")
        self.status.setText("识别成功")
        self.rule_changed.emit()

    def _save_rule(self, rule: dict) -> None:
        rules = list(self.config.get("custom_rules") or [])
        m = rule.get("match") or {}
        rules = [r for r in rules if not _same_match(r.get("match") or {}, m)]
        rules.append(rule)
        self.config.set("custom_rules", rules)

    # ---------------- 诊断报告 ----------------
    def _export_report(self) -> None:
        """把当前能采集到的全部信息写成一份 txt。

        软件发给别人后，他那台读不到设备时，一句"导出报告发我"就能定位：
        报告里带每个 HID 端点、每个系统电池设备的实例 ID、读数状态和失败原因，
        不需要再靠来回猜型号。
        """
        import platform
        from datetime import datetime

        from config import config_dir
        from scanner import Scanner

        self.status.setText("正在收集诊断信息…")
        QGuiApplication.processEvents()

        devices: list[Device] = []
        debug: list[str] = []
        try:
            devices, debug = Scanner(self.config).scan(with_debug=True, force=True)
        except Exception as exc:
            debug = [f"扫描异常: {type(exc).__name__}: {exc}"]

        eps = raw_hid.describe_endpoints()
        self.endpoints = eps

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

        lines += ["", f"【二、HID 端点】共 {len(eps)} 个（★ = 厂商协议通道，电量候选）"]
        for ep in eps:
            lines.append(
                f"{ep['vendor_id']:04X}:{ep['product_id']:04X} | "
                f"{describe_vendor(ep['vendor_id'])} | "
                f"{ep['manufacturer'] or '-'} | {ep['product'] or '-'} | "
                f"页=0x{(ep['usage_page'] or 0):04X} 用法=0x{(ep['usage'] or 0):04X} | "
                f"{'★ ' if ep.get('recommend') else ''}{ep.get('role') or '-'} | "
                f"接口={ep['interface']}")

        lines += ["", f"【三、扫描日志】共 {len(debug)} 行"]
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

        self._devices = devices
        self._debug = debug
        self.update_devices(devices, debug)
        self.status.setText(f"已导出：{path}")
        QMessageBox.information(
            self, "诊断报告已导出",
            f"已保存到：\n{path}\n\n把这个 txt 整份发回来即可定位问题。")


def _same_match(a: dict, b: dict) -> bool:
    return (
        a.get("vendor_id") == b.get("vendor_id")
        and a.get("product_id") == b.get("product_id")
        and a.get("usage_page") == b.get("usage_page")
        and a.get("usage") == b.get("usage")
    )
