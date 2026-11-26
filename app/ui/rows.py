# -*- coding: utf-8 -*-
"""诊断页与添加窗口共用的行样式与容器骨架。

为什么不用 QTableWidget：表头、网格线、列宽拖拽都是"表格"语义，而这里
每一行其实是一台设备。换成行卡片之后，同一个样式既能用在结果列表里，
也能用在添加窗口的接收器列表里，两个窗口看起来才是一套东西。

行只有三块，不再多塞任何说明：
    [图标]  名称 / 一行来源        [85%]
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

import theme
from ui.widgets import DeviceIconTile, ElidedLabel, PercentLabel

ROW_HEIGHT = 54


def setup_dialog(window: QWidget, min_size: tuple[int, int]) -> None:
    """诊断页 / 添加设备共用的窗口骨架。

    两个窗口必须长得像一套：同一块底色、同一套标题配色、同样的置顶策略。
    以前各写一遍，改一处忘了另一处就会"一个白底一个黑底"。
    """
    window.setObjectName("DiagRoot")
    window.setStyleSheet(theme.qss())
    window.setMinimumSize(*min_size)
    window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)


def scroll_list(spacing: int = 2) -> tuple[QScrollArea, QVBoxLayout]:
    """透明滚动区 + 一个已带底部伸缩的垂直列表布局。

    卡片本身是窗口底色，滚动区再画自己的框和底色就会多出一层边；
    所以视图与容器都设成透明，只让滚动条可见。
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.viewport().setAutoFillBackground(False)

    holder = QWidget()
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 4, 0)
    lay.setSpacing(spacing)
    lay.addStretch(1)
    area.setWidget(holder)
    return area, lay


def clear_layout(layout) -> None:
    """清空一个列表布局：控件摘下来排进删除队列，伸缩项直接丢掉。

    诊断页与添加窗口都用"每次重画整张列表"的做法，两边各写一遍容易漏掉
    `setParent(None)` —— 只 deleteLater 的话控件在事件循环转回来之前仍然
    挂在原处，重画时会短暂叠在旧行上。
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


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


__all__ = ["Row", "PickRow", "ROW_HEIGHT", "clear_layout", "scroll_list", "setup_dialog"]
