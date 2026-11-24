# -*- coding: utf-8 -*-
"""【鼠标】英菲克 ZHEN、DELUX M900 Pro

适配设备
    英菲克 ZHEN        1D57:FA65 接收器，帧头 76 41
    DELUX M900 Pro     1D57:FA65 接收器，帧头 30 40
    两家共用同一颗接收器方案，号段完全一样，只能靠帧头认。

怎么读
    纯被动，一帧都不写。4 字节状态包：
    [2] 标志（0x01 放电 / 0x03 充电；DELUX 另有 0x02 满电）、[3] 电量。

注意
    满电搁在底座上时标志会在 0/1/2 之间横跳，100% 且不是放电一律按
    "不在充电"处理，否则托盘图标会一直闪闪电。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

INPHIC_VID = 0x1D57
INPHIC_PID = 0xFA65
DELUX_PAGE = 0x000A          # 同一只接收器上 DELUX 那条集合的 usage page


def match(ctx: Ctx) -> bool:
    return ctx.vid == INPHIC_VID and ctx.pid == INPHIC_PID


def _parse(raw: bytes):
    """一帧里认出属于哪家。返回 (label, model, flag, percent) 或 None。"""
    for off in (0, 1):
        if len(raw) < off + 4:
            continue
        head = (raw[off], raw[off + 1])
        if head == (0x76, 0x41):
            label, model = "协议包·英菲克", "英菲克 ZHEN"
        elif head == (0x30, 0x40):
            label, model = "协议包·DELUX", "DELUX M900 Pro"
        else:
            continue
        percent = raw[off + 3]
        if percent > 100:
            return None
        return label, model, raw[off + 2], percent
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=0xFF00, usage_=0x0001) + ctx.pick(page_=DELUX_PAGE)
    if not targets:
        targets = ctx.members[:2]
    key = ("inphic", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = base.wait_for(dev, _parse, ms=1500, size=16)
            if hit is None:
                continue
            base.clear_fail(key)
            label, model, flag, percent = hit
            # 英菲克 0x01 放电 / 0x03 充电；DELUX 再加 0x02 满电
            charging = flag == 0x03
            if percent >= 100 and flag != 0x01:
                charging = False        # 满电别在托盘上一直显示充电
            return Reading(percent, charging, label=label, model=model)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
