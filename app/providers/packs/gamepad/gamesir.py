# -*- coding: utf-8 -*-
"""【手柄】盖世小鸡 GameSir G7 Pro

适配设备
    GameSir G7 Pro    3537，配置通道 0xFFF0，状态流 report 0x12

怎么读
    电量在 [36]、充电在 [35]。不发心跳时 0x12 是空帧；在配置通道发一帧
    `0F F2 00`，状态流立刻涌出约 2 秒。官方客户端每秒一帧心跳维持它，
    这里按"一次轮询发一帧、读一小段"来用，写入量与官方同量级。

注意
    刻意不拆 bit7：官方对这条流就是把 [36] 当百分比、[35]==1 当充电中。
    "电量字节 bit7 = 充电"属于另一条 getDeviceInfo 路径的编码，混用会把
    100% 读成"充电中 0%"。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3537
CONFIG_PAGE = 0xFFF0
STATE_REPORT_ID = 0x12
CHARGE_OFFSET = 35
PERCENT_OFFSET = 36
HEARTBEAT_ID = 0x0F
HEARTBEAT_CMD = 0xF2


def match(ctx: Ctx) -> bool:
    return ctx.vid == VID and bool(ctx.pick(page_=CONFIG_PAGE))


def parse(raw: bytes):
    if len(raw) < PERCENT_OFFSET + 1 or raw[0] != STATE_REPORT_ID:
        return None
    percent = raw[PERCENT_OFFSET]
    if percent == 0 or percent > 100:
        return None
    return percent, raw[CHARGE_OFFSET] == 1


def heartbeat() -> bytes:
    frame = bytearray(64)
    frame[0] = HEARTBEAT_ID
    frame[1] = HEARTBEAT_CMD
    return bytes(frame)


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=CONFIG_PAGE)
    if not targets:
        return None
    key = ("gamesir", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            base.write(dev, heartbeat())
            hit = base.wait_for(dev, parse, ms=1000)
            if hit is None:
                continue
            base.clear_fail(key)
            percent, charging = hit
            return Reading(percent, charging, label="协议包·盖世小鸡",
                           model=_clean(ctx.name) or "GameSir G7 Pro",
                           kind=base.GAMEPAD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None


def _clean(name: str) -> str:
    text = (name or "").strip()
    for brand in ("GameSir", "GAMESIR", "Gamesir", "盖世小鸡"):
        if text.lower().startswith(brand.lower()):
            return text[len(brand):].strip(" -_")
    return text
