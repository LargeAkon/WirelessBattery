# -*- coding: utf-8 -*-
"""HyperX Cloud Flight 2（03F0:0AC1，状态流接口 0xFF90）：纯被动，零写入。

这不是老 Cloud Flight 的电压帧（0x21 0xFF 0x05），CF2 换了状态帧协议：
    FB 09 01/00   插线 / 拔线（充电状态事件）
    FB 0A 01/00   耳机在线 / 离线
    FB 13 <pct>   电量帧（每变化 1% 推一条）
    51 02 <pct>   开机/重连时的完整状态帧
    45 02 …       常驻心跳，无电量
    FF 01 … 44    官方软件的通信往返，同样无电量

心跳常驻但电量帧稀疏（只在变化时推），所以被动窗口给 2.5 秒；
拿不到就这一轮不认领，下一轮再试。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x03F0
PID = 0x0AC1
PAGE = 0xFF90
EVENT = 0xFB
SUB_CHARGE = 0x09
SUB_POWER = 0x0A
SUB_BATTERY = 0x13
LEVEL_INDEX = 3


def match(ctx: Ctx) -> bool:
    return ctx.vid == VID and ctx.pid == PID and bool(ctx.pick(page_=PAGE))


def _is_heartbeat(raw: bytes) -> bool:
    if len(raw) < 2:
        return False
    if raw[0] == 0x45 and raw[1] == 0x02:
        return True
    return raw[0] == 0xFF and len(raw) > 15 and raw[14] == 0x44


def parse(raw: bytes):
    """返回 (电量, 是否充电) 或 None。充电事件单独成帧，故电量帧带 None。"""
    if raw is None or len(raw) < 4 or _is_heartbeat(raw):
        return None
    if raw[0] == 0x51 and raw[1] == 0x02:
        percent = raw[2]
        if 0 <= percent <= 100:
            return percent, None
        return None
    if raw[0] != EVENT:
        return None
    if raw[1] == SUB_CHARGE:
        return None, raw[2] == 0x01
    if raw[1] == SUB_BATTERY:
        percent = raw[LEVEL_INDEX]
        if 0 <= percent <= 100:
            return percent, None
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE)
    if not targets:
        return None
    key = ("hyperx_cf2", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            percent = None
            charging = None
            for _ in range(20):               # 约 2.5 秒
                raw = base.read(dev, 130)
                if raw is None:
                    continue
                hit = parse(raw)
                if hit is None:
                    continue
                if hit[0] is not None:
                    percent = hit[0]
                    if hit[1] is not None:
                        charging = hit[1]
                    break
                if charging is None and hit[1] is not None:
                    charging = hit[1]
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·HyperX",
                           model="HyperX Cloud Flight 2", kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
