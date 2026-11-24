# -*- coding: utf-8 -*-
"""【鼠标】派世 Pulsar X2 V2

适配设备
    Pulsar X2 V2      3554，接口 0xFF02，17 字节厂商帧（report 0x08）

怎么读
    校验 = (0x55 − 前 16 字节之和) & 0xFF，帧尾放校验。
    STATUS(0x03)  [6] = 1 表示设备在线
    POWER(0x04)   [6] = 电量  [7] = 充电  [8..9] = 电压 mV（大端）
    先问 STATUS 再问 POWER：dongle 在位但鼠标没连上时不该出现在列表里。

来源
    Linux 内核 hid-pulsar 驱动；本机实测 20% / 3570 mV。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3554
VENDOR_PAGE = 0xFF02
REPORT_ID = 0x08
FRAME_LEN = 17
CMD_STATUS = 0x03
CMD_POWER = 0x04
SEED = 0x55


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if not (ctx.pick(page_=VENDOR_PAGE) or ctx.pick(usage_=VENDOR_PAGE)):
        return False
    return bool(ctx.pick(page_=VENDOR_PAGE) or ctx.pick(usage_=VENDOR_PAGE))


def checksum(frame: bytes) -> int:
    return (SEED - sum(frame[:-1])) & 0xFF


def build(command: int) -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[0] = REPORT_ID
    frame[1] = command
    frame[-1] = (SEED - sum(frame[:-1])) & 0xFF
    return bytes(frame)


def _reply(command: int):
    def parse(raw: bytes):
        if len(raw) != FRAME_LEN:
            return None
        if raw[0] != REPORT_ID or raw[1] != command:
            return None
        if raw[-1] != checksum(raw):
            return None            # 休眠时接口可能吐半截帧
        return raw
    return parse


def _query(dev, command: int):
    base.drain(dev)
    if not base.write(dev, build(command)):
        return None
    return base.wait_for(dev, _reply(command), ms=1200, size=FRAME_LEN)


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=VENDOR_PAGE) or ctx.pick(usage_=VENDOR_PAGE)
    if not targets:
        return None
    key = ("pulsar", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            status = _query(dev, CMD_STATUS)
            if status is None or status[6] != 1:
                continue                      # 设备没连上
            power = _query(dev, CMD_POWER)
            if power is None:
                continue
            percent = power[6]
            if percent > 100:
                continue
            base.clear_fail(key)
            charging = power[7] == 1
            name = (ctx.name or "").replace("Dongle", "").strip()
            return Reading(percent, charging, label="协议包·派世",
                           model=f"派世 {name}".strip() or "派世 X2 V2",
                           kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
