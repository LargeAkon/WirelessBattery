# -*- coding: utf-8 -*-
"""3554:FA09 会话协议：三家键盘共用的一段。

AULA F99 Pro、凌豹 K98、迈从 G75 装在同一个芯片方案上，HID 层完全同指纹
（接口 0xFF02/0x0002，输入输出都是 20 字节）。分辨谁是谁只能靠会话 ACK 里的
**型号码**：
    AULA F99 Pro    0x0158
    凌豹 K98        0x0212
    迈从系          用 6 字节型号密码查表（见 keyboard/mchose.py）

所以协议帧的构造与解析放在这里，各品牌文件只写"我的型号码是多少"。
这不是注册表里的通道，文件名带下划线表示内部共享模块，不会被单独扫描。
"""
from __future__ import annotations

from providers.packs import base

VID = 0x3554
PID = 0xFA09
PAGE = 0xFF02
USAGE = 0x0002
RID = 0x13
SESSION = 0x05
QUERY = 0x4A
PUSH = 0x0A
PUSH_BATTERY = 0x05
LEN = 20


def targets(ctx) -> list[dict]:
    """该接收器上承载会话协议的接口。"""
    return [m for m in ctx.pick(page_=PAGE, usage_=USAGE)
            if base.io_lengths(m) == (LEN, LEN)]


def frame(command: int, param: int) -> bytes:
    out = bytearray(LEN)
    out[0] = RID
    out[1] = command
    out[2] = param
    out[-1] = sum(out[:-1]) & 0xFF
    return bytes(out)


def model_code(raw: bytes):
    """会话 ACK 里的型号码；不是 ACK 帧返回 None。"""
    for off in (0, 1):
        if len(raw) < off + 12:
            continue
        if raw[off] != RID or raw[off + 1] != SESSION or raw[off + 2] != 0x01:
            continue
        return (raw[off + 9] << 8) | raw[off + 10]
    return None


def read(raw: bytes):
    """0A 电量推送 / 4A 应答 → (电量, 是否充电) 或 None。"""
    for off in (0, 1):
        if len(raw) < off + 8:
            continue
        if raw[off] != RID:
            continue
        if raw[off + 1] == PUSH:
            if raw[off + 5] != PUSH_BATTERY:
                return None
            percent, flag = raw[off + 6], raw[off + 7]
        elif raw[off + 1] == QUERY:
            if len(raw) < LEN:
                return None
            percent, flag = raw[off + 5], raw[off + 6]
        else:
            return None
        if percent <= 1 or percent > 100:     # 0/1 是休眠占位
            return None
        return percent, bool(flag & 0x10)
    return None
