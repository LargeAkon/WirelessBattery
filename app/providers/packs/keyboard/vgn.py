# -*- coding: utf-8 -*-
"""【键盘】VGN V98 Pro

适配设备
    VGN V98 Pro     320F:5088，接口 0xFF1C/0x0092，输出 ≥17 字节

怎么认
    接口指纹之外还要产品名自证：320F:5088 这个号段被 VGN 多款键盘共用
    （V98 Pro / VXE75 系），0xFF1C/0x0092 接口与报文长度完全一样，
    只看指纹会把 VXE75 也认成 V98 Pro，同一只接收器就会出现两行、名字还不一样。
        - 产品名含 V98      → 认领
        - 产品名含 VXE/VGN  → 让位（VXE75 走 Evision 芯片通道）
        - 产品名读不到      → 按接口认，不做二次猜测

怎么读
    请求 `04 00 00 1A 06 00 00 00`
    应答 [0]=0x04、[3]=0x1A 才算电量帧，电量在 [8]、充电在 [9]。

注意
    VGN 的鼠标链路（蜻蜓 F1 / F2）在 mouse/vgn.py。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x320F
PID = 0x5088
PAGE = 0xFF1C
USAGE = 0x0092
RID = 0x04
MIN_OUT = 17
QUERY = bytes([0x00, 0x00, 0x1A, 0x06, 0x00, 0x00, 0x00])


def match(ctx: Ctx) -> bool:
    return _is_v98(ctx)


def _is_v98(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not any(base.io_lengths(m)[1] >= MIN_OUT for m in targets):
        return False
    name = (ctx.name or "").upper()
    if "V98" in name:
        return True
    if "VXE" in name or "VGN" in name:
        return False                     # 明确是别的型号（如 VXE75），让给 Evision
    return True                          # 读不到产品名时按接口认，不做二次猜测


def build_query(length: int) -> bytes:
    frame = bytearray(max(length, len(QUERY) + 1))
    frame[0] = RID
    frame[1:1 + len(QUERY)] = QUERY
    return bytes(frame)


def parse(raw: bytes):
    if len(raw) <= 9:
        return None
    if raw[0] != RID or raw[3] != 0x1A:
        return None
    percent = raw[8]
    if percent > 100:
        return None
    return percent, raw[9] != 0


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("vgn-kb", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            length = base.io_lengths(member)[1]
            if not base.write(dev, build_query(length)):
                continue
            hit = base.wait_for(dev, parse, ms=900, size=max(length, MIN_OUT))
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·VGN",
                           model="VGN V98 Pro", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
