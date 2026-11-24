# -*- coding: utf-8 -*-
"""HECATE（漫步者电竞）G5M Pro：35BB:D00B，report 0x04 状态帧。

状态帧布局（docs 与 Connect 命令表一致）：
    [0]=0x04  [3]=0x1A 标记  [8]=电量  [9]=充电标志
充电标志在这一家是 0x01=充电、0x02=满、0x00=放电 —— 与英菲克相反。

被动流在 Connect 关闭时是静的，所以要一条查询帧（同样的 0x04 + 0x1A）：
设备收到即刻回状态帧，实测 <1ms。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x35BB
PID = 0xD00B
REPORT_LEN = 64
REPORT_ID = 0x04
MARKER_INDEX = 3
MARKER = 0x1A
PERCENT_INDEX = 8
FLAG_INDEX = 9


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=0xFF1C, usage_=0x0092))


def parse(raw: bytes):
    if len(raw) < REPORT_LEN or raw[0] != REPORT_ID or raw[MARKER_INDEX] != MARKER:
        return None
    percent = raw[PERCENT_INDEX]
    if percent == 0 or percent > 100:       # 0 是休眠/唤醒瞬态
        return None
    flag = raw[FLAG_INDEX]
    if percent >= 100:
        return percent, False
    return percent, flag == 0x01


def query_frame() -> bytes:
    frame = bytearray(REPORT_LEN)
    frame[0] = REPORT_ID
    frame[MARKER_INDEX] = MARKER
    return bytes(frame)


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=0xFF1C, usage_=0x0092)
    if not targets:
        return None
    key = ("hecate", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            base.write(dev, query_frame())
            hit = base.wait_for(dev, parse, ms=750)
            if hit is None:
                # 查询没回音也可能只是没开主动流，再被动听一小段
                hit = base.wait_for(dev, parse, ms=600)
            if hit is None:
                continue
            base.clear_fail(key)
            percent, charging = hit
            return Reading(percent, charging, label="协议包·HECATE",
                           model=ctx.name or "HECATE G5M Pro", kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
