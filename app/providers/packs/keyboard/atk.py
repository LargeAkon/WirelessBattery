# -*- coding: utf-8 -*-
"""【键盘】ATK / VXE 系列无线键盘（标准 VIA 通道）

适配设备
    ATK / VXE 支持 VIA 的无线键盘    373B，接口 0xFF60
    这条链路不绑型号：只要键盘固件开了 VIA 自定义通道，就能读到电量。
    ATK 的鼠标链路在同目录上一级的 mouse/atk.py，两者互不干扰。

怎么认
    接口 0xFF60，输入输出等长（VIA 通道的典型形态）。

怎么读
    VIA 自定义通道 0x96 的电量键 0x24：
        请求 `[rid] 02 96 24`
        应答 `02 96 24 <电量> <充电>`

注意
    电量 0 判无效（设备未就绪时也会回结构合法的 0）。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x373B
VIA_PAGE = 0xFF60


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    return bool(ctx.pick(page_=VIA_PAGE))


def build_query(length: int) -> bytes:
    frame = bytearray(max(length, 5))
    frame[0] = 0x00
    frame[1] = 0x02
    frame[2] = 0x96
    frame[3] = 0x24
    return bytes(frame)


def parse(raw: bytes):
    for off in (1, 0):
        if len(raw) < off + 5:
            continue
        frame = raw[off:]
        if frame[0] != 0x02 or frame[1] != 0x96 or frame[2] != 0x24:
            continue
        percent = frame[3]
        if percent == 0 or percent > 100:
            continue
        return percent, frame[4] != 0
    return None


def _model_name(ctx: Ctx) -> str:
    name = (ctx.name or "").replace("ATK", "").replace("Wireless", "").strip()
    return f"ATK {name}".strip() if name else "ATK / VXE 无线键盘"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=VIA_PAGE)
    if not targets:
        return None
    member = targets[0]
    key = ("atk-kb", ctx.phys)
    if base.cooled(key, force):
        return None

    dev = None
    try:
        dev = base.open_member(member)
        base.drain(dev)
        length = base.io_lengths(member)[1] or 32
        if not base.write(dev, build_query(length)):
            base.mark_fail(key)
            return None
        hit = base.wait_for(dev, parse, ms=900, size=max(length, 33))
        if hit is None:
            base.mark_fail(key)
            return None
        base.clear_fail(key)
        return Reading(hit[0], hit[1], label="协议包·ATK",
                       model=_model_name(ctx), kind=base.KEYBOARD,
                       transport="2.4G 接收器 / USB 有线")
    except Exception:
        base.mark_fail(key)
        return None
    finally:
        base.close(dev)
