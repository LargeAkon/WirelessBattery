# -*- coding: utf-8 -*-
"""【键盘】前行者 EWEADN X87

适配设备
    前行者 X87      0C45:FEFE，接口 0xFF60/0x0061

怎么认
    只看 VID:PID + 0xFF60/0x0061 这一组接口，同系列的鼠标不走这个号段。

怎么读
    33 字节输出帧：`00 20 01 …校验`，校验 = 全部字节求和取低 8 位，放在 [32]。
    应答 [3] 是电量。

注意
    官方驱动把充电位固定传 0，这里跟着官方走 —— 不报告充电状态，
    而不是自己猜一个。
    电量 0 表示设备未就绪，判无效。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x0C45
PID = 0xFEFE
PAGE = 0xFF60
USAGE = 0x0061
FRAME_LEN = 33


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=PAGE, usage_=USAGE))


def build_query() -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[1] = 0x20
    frame[2] = 0x01
    frame[FRAME_LEN - 1] = sum(frame) & 0xFF
    return bytes(frame)


def parse(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 4:
            continue
        if raw[off] != 0x20 or raw[off + 1] != 0x01:
            continue
        percent = raw[off + 3]
        if percent == 0:            # 0 = 设备未就绪，不是电量
            return None
        return min(100, percent)
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("eweadn-kb", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, build_query()):
                continue
            percent = base.wait_for(dev, parse, ms=1500)
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, None, label="协议包·前行者",
                           model="前行者 X87", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
