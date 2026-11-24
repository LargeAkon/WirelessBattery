# -*- coding: utf-8 -*-
"""黑爵 AJAZZ AK870（ROYUAN 接收器 3151:4011）。

邮箱式 feature，report ID 恒 0：
    写 64 字节查询（[0]=0xF7、[7]=0x08）→ 等 100ms → 读回 65 字节
应答布局：`00 <ack> <电量> ? <在线> …`，[4]==0 表示设备在线。
没有充电位，充电态交给统一的收尾规则（100% 且未充电 ⇒ 满）。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3151
PID = 0x4011
PAGE = 0xFFFF
USAGE = 0x0002
FEATURE_ID = 0x00
FEATURE_LEN = 65


def match(ctx: Ctx) -> bool:
    return (ctx.vid == VID and ctx.pid == PID
            and bool(ctx.pick(page_=PAGE, usage_=USAGE)))


def query_frame() -> bytes:
    payload = bytearray(64)
    payload[0] = 0xF7
    payload[7] = 0x08
    return bytes(payload)


def parse(raw: bytes):
    if len(raw) not in (64, 65) or raw[0] != 0:
        return None
    if raw[1] > 1 or raw[2] > 100:
        return None
    if raw[4] > 1 or raw[5] > 1 or raw[6] > 1 or raw[7] not in (1, 3):
        return None
    if raw[4] != 0:                 # 设备没连上
        return None
    return raw[2]


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("ajazz", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            reply = base.feature_roundtrip(dev, FEATURE_ID, query_frame(),
                                           FEATURE_LEN, wait_ms=100)
            percent = parse(reply) if reply else None
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, None, label="协议包·黑爵",
                           model="黑爵 AK870", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
