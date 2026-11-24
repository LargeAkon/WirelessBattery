# -*- coding: utf-8 -*-
"""诊断页与添加窗口共用的行样式：图标 + 名称/副文本 + 右侧状态。

为什么不用 QTableWidget：表头、网格线、列宽拖拽都是"表格"语义，而这里
每一行其实是一台设备。换成行卡片之后，同一个样式既能用在结果列表里，
也能用在添加窗口的接收器列表里，两个窗口看起来才是一套东西。

行只有三块，不再多塞任何说明：
    [图标]  名称 / 一行来源        [85%]
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets import DeviceIconTile, ElidedLabel, PercentLabel

ROW_HEIGHT = 54


def _repolish(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class Row(QFrame):
    """一行设备/接收器。默认不可点；子类 PickRow 才响应点击。"""

    def __init__(self, name: str = "", sub: str = "", kind: str = "unknown",
                 dim: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Row")
        self.setFixedHeight(ROW_HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 6, 12, 6)
        lay.setSpacing(11)

        self.tile = DeviceIconTile(_Kind(kind), dim=dim)
        lay.addWidget(self.tile, 0, Qt.AlignVCenter)

        block = QWidget()
        mid = QVBoxLayout(block)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(2)
        self.name_label = ElidedLabel(name)
        self.name_label.setObjectName("RowSub" if dim else "RowName")
        mid.addWidget(self.name_label)
        self.sub_label = ElidedLabel(sub)
        self.sub_label.setObjectName("RowSub")
        self.sub_label.setVisible(bool(sub))
        mid.addWidget(self.sub_label)
        lay.addWidget(block, 1, Qt.AlignVCenter)

        self.percent = PercentLabel()
        self.percent.setVisible(False)
        lay.addWidget(self.percent, 0, Qt.AlignVCenter)

        self.state_label = QLabel("")
        self.state_label.setObjectName("RowStateDim" if dim else "RowState")
        self.state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.state_label.setVisible(False)
        lay.addWidget(self.state_label, 0, Qt.AlignVCenter)

        self._dim = dim

    # ---------------- 内容 ----------------
    def set_name(self, text: str) -> None:
        self.name_label.setText(text)

    def set_sub(self, text: str) -> None:
        self.sub_label.setText(text)
        self.sub_label.setVisible(bool(text))
        self.sub_label.setToolTip(text)

    def set_kind(self, kind: str) -> None:
        self.tile.device = _Kind(kind)
        self.tile.update()

    def show_percent(self, text: str) -> None:
        self.state_label.setVisible(False)
        self.percent.setVisible(True)
        self.percent.set_value(text)

    def show_state(self, text: str) -> None:
        self.percent.setVisible(False)
        self.state_label.setVisible(True)
        self.state_label.setText(text)
        self.state_label.setToolTip(text)


class PickRow(Row):
    """可点的行（添加窗口里选接收器）。点一下就是选中，不做双击。"""

    picked = Signal()

    def __init__(self, name: str = "", sub: str = "", kind: str = "unknown", parent=None):
        super().__init__(name, sub, kind, parent=parent)
        self.setObjectName("PickRow")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("picked", False)

    def set_picked(self, on: bool) -> None:
        if bool(self.property("picked")) == bool(on):
            return
        self.setProperty("picked", bool(on))
        _repolish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.picked.emit()
        super().mousePressEvent(event)


class _Kind:
    """图标磁贴只读 .kind，这里给个最小替身，省得为"读不到"的行造一个假设备。"""

    __slots__ = ("kind",)

    def __init__(self, kind: str):
        self.kind = kind or "unknown"


__all__ = ["Row", "PickRow", "ROW_HEIGHT"]
