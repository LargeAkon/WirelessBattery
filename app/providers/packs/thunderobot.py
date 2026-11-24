# -*- coding: utf-8 -*-
"""雷神 THUNDEROBOT ML903 NearLink Se（369B:0234）：0xA0 设备信息 TLV。

查询 `A0 02` 打出去，设备回 `A1 02` + 一串 TLV：
    0x0204 → 2 字节、0x0211 → 4、0x0213 → 6、0x0225 → 1、0x0226 → 1
电量在 0x0225 这个标签后面那一字节。遇到 0 字节表示列表结束，其后必须
全 0；标签不认识或长度越界就整帧作废 —— 宁可不上报，也不把配置字节
当电量。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x369B
PID = 0x0234
PAGE = 0xFFA0
USAGE = 0x0002
REPORT_ID = 0xA0
REPLY_ID = 0xA1
SUB = 0x02
FRAME_LEN = 64

_TAG_LENGTH = {0x0204: 2, 0x0211: 4, 0x0213: 6, 0x0225: 1, 0x0226: 1}


def match(ctx: Ctx) -> bool:
    return (ctx.vid == VID and ctx.pid == PID
            and bool(ctx.pick(page_=PAGE, usage_=USAGE)))


def query_frame() -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[0] = REPORT_ID
    frame[1] = SUB
    return bytes(frame)


def parse(raw: bytes):
    if len(raw) != FRAME_LEN or raw[0] != REPLY_ID or raw[1] != SUB:
        return None
    percent = None
    offset = 1
    while offset < len(raw):
        if raw[offset] == 0:
            if any(raw[offset:]):
                return None                  # 结束标记后面还有东西 → 帧坏了
            return percent
        if offset + 2 > len(raw):
            return None
        tag = (raw[offset] << 8) | raw[offset + 1]
        length = _TAG_LENGTH.get(tag, 0)
        if length == 0 or offset + 2 + length > len(raw):
            return None
        if tag == 0x0225:
            value = raw[offset + 2]
            if percent is not None or value > 100:
                return None
            percent = value
        offset += 2 + length
    return percent


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("thunderobot", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, query_frame()):
                continue
            percent = base.wait_for(dev, parse, ms=800, size=FRAME_LEN)
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, None, label="协议包·雷神",
                           model="雷神 ML903 NearLink Se", kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
