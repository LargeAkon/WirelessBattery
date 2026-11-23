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
    # "046D:C547" 形式。同一个物理设备会被多条通道同时看到（接收器的
    # 厂商协议 + 系统电池设备），跨通道去重靠它，不靠名字 —— 系统通道
    # 拿到的名字往往是 "HID-compliant mouse"，和厂商通道对不上。
    vid_pid: str = ""

    @property
    def type_label(self) -> str:
        return TYPE_LABEL.get(self.kind, TYPE_LABEL[UNKNOWN])

    @property
    def percent_text(self) -> str:
        if self.level is None:
            return "--"
        return str(int(round(self.level)))

    @property
    def meta_text(self) -> str:
        parts = [self.type_label]
        state = (self.raw or {}).get("state")
        if self.charging:
            parts.append("充电中")
        elif self.level is None:
            if state == "无电量接口":
                # 接收器确实在，但固件不提供电量通道 —— 说清楚，别让人以为在等应答
                parts.append("不提供电量")
            elif state == "超时":
                parts.append("信号中断")
            else:
                parts.append("设备休眠" if state == "休眠" else "等待应答")
        elif state == "超时":
            # 数值是上一次成功读到的，不是刚读到的 —— 必须讲清楚，否则会被当成实时值
            parts.append("信号中断 · 上次读数")
        elif self.level <= 15:
            parts.append("电量告急")
        elif self.level <= 30:
            parts.append("电量偏低")
        if self.transport:
            parts.append(self.transport)
        return " · ".join(parts)

    def sort_key(self):
        order = {MOUSE: 0, KEYBOARD: 1, HEADSET: 2, GAMEPAD: 3, UNKNOWN: 4}
        return (order.get(self.kind, 3), self.name)

    def signature(self) -> tuple:
        return (self.key, self.name, self.kind, self.level, self.charging)
