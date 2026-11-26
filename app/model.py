# -*- coding: utf-8 -*-
"""统一设备模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

# 设备类型
MOUSE = "mouse"
KEYBOARD = "keyboard"
HEADSET = "headset"
GAMEPAD = "gamepad"
UNKNOWN = "unknown"

TYPE_LABEL = {
    MOUSE: "无线鼠标",
    KEYBOARD: "无线键盘",
    HEADSET: "无线耳机",
    GAMEPAD: "无线手柄",
    UNKNOWN: "无线外设",
}


@dataclass
class Device:
    """一个可显示电量的外设。

    key       : 稳定标识，用于记住用户偏好与去重
    name      : 显示名
    kind      : mouse / keyboard / headset / gamepad / unknown
    level     : 0-100，None 表示未知
    charging  : 是否在充电
    source    : 探测通道来源，用于诊断
    transport : 连接方式描述
    """

    key: str
    name: str
    kind: str = UNKNOWN
    level: float | None = None
    charging: bool = False
    source: str = ""
    transport: str = ""
    raw: dict = field(default_factory=dict)
    # "046D:C547" 形式。同一个物理设备会被多条通道同时看到（协议包与芯片组、
    # 或用户添加的协议），跨通道去重靠它，不靠名字 —— 接收器报上来的名字
    # 往往是 "USB Receiver"，各通道写法对不上。
    vid_pid: str = ""

    @property
    def type_label(self) -> str:
        return TYPE_LABEL.get(self.kind, TYPE_LABEL[UNKNOWN])

    @property
    def percent_text(self) -> str:
        if self.level is None:
            return "--"
        return str(int(round(self.level)))

    def sort_key(self):
        """列表顺序：类型 → 名字。"""
        order = {MOUSE: 0, KEYBOARD: 1, HEADSET: 2, GAMEPAD: 3, UNKNOWN: 4}
        # 兜底也必须是"未知"那一档；以前写死 3，等于把认不出的设备
        # 排到手柄堆里（顺序会莫名其妙地跳）。
        return (order.get(self.kind, order[UNKNOWN]), self.name)
