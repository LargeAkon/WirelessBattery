# -*- coding: utf-8 -*-
"""CHERRY PIXIU75：64 字节厂商块帧（report 0x04）。

帧头 8 字节：ID / 令牌(恒 0) / 块号 / 长度 / 偏移低 / 偏移高 / 保留，
payload 从 [8] 起。电力块 0x1A 的 payload[0] 是百分比、payload[1] 最低位是
充电位（插线时官方软件同时画闪电）。

令牌只验证过 0，这里不引入未验证的令牌值（safety 规则 1）。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x046A
VENDOR_PAGE = 0xFF1C
REPORT_ID = 0x04
FRAME_LEN = 64
PAYLOAD_OFFSET = 8
BLOCK_BATTERY = 0x1A
BLOCK_DEVICE_INFO = 0x1D


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    targets = ctx.pick(page_=VENDOR_PAGE) or ctx.pick(usage_=VENDOR_PAGE)
    return bool(targets)


def build_request(block: int, length: int, offset: int = 0) -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[0] = REPORT_ID
    frame[3] = block
    frame[4] = length
    frame[5] = offset & 0xFF
    frame[6] = (offset >> 8) & 0xFF
    return bytes(frame)


def _reply(block: int):
    def parse(raw: bytes):
        if len(raw) < PAYLOAD_OFFSET or raw[0] != REPORT_ID or raw[3] != block:
            return None
        length = raw[4]
        if length == 0:
            return None
        available = len(raw) - PAYLOAD_OFFSET
        return raw[PAYLOAD_OFFSET:PAYLOAD_OFFSET + min(length, available)]
    return parse


def _request_block(dev, block: int, length: int):
    if not base.write(dev, build_request(block, length)):
        return None
    return base.wait_for(dev, _reply(block), ms=1200)


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=VENDOR_PAGE) or ctx.pick(usage_=VENDOR_PAGE)
    if not targets:
        return None
    key = ("cherry", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            payload = _request_block(dev, BLOCK_BATTERY, 4)
            if payload is None or not payload or payload[0] > 100:
                continue
            base.clear_fail(key)
            percent = payload[0]
            charging = len(payload) > 1 and (payload[1] & 0x01) != 0
            name = (ctx.name or "").replace("Dongle", "").strip()
            return Reading(percent, charging, label="协议包·CHERRY",
                           model=f"CHERRY {name}".strip() or "CHERRY PIXIU75",
                           kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
