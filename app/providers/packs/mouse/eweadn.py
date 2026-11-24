# -*- coding: utf-8 -*-
"""【鼠标】前行者 EWEADN S9

适配设备
    前行者 S9       372E:1026，接口 0xFF00/0x0001

怎么认
    VID 0x372E 与键盘 X87 的 0x0C45 不同号段，只看接口指纹即可。

怎么读
    邮箱式 feature（report ID 0x03）：
        先写 63 字节 BASICS 查询（0x4F/0x81，CRC 在 payload[0]），
        等 20ms 再读同一个 feature。
    应答 [6]：bit7 = 充电中、低 7 位 = 百分比。

注意
    休眠时设备会回结构合法的 0，电量 0 一律判无效。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x372E
PID = 0x1026
PAGE = 0xFF00
USAGE = 0x0001
FEATURE_ID = 0x03
FRAME_LEN = 63


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=PAGE, usage_=USAGE))


def build_query() -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[1] = 0x50
    frame[2] = 0x00
    frame[3] = 0x02
    frame[4] = 0x4F
    frame[5] = 0x81
    frame[0] = sum(frame[1:]) & 0xFF     # CRC 从下标 1 起算
    return bytes(frame)


def parse(raw: bytes):
    if len(raw) < 7:
        return None
    if raw[0] != FEATURE_ID or raw[1] != 0x50:
        return None
    value = raw[6]
    percent = value & 0x7F
    if percent == 0 or percent > 100:
        return None
    return percent, (value & 0x80) != 0


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("eweadn-ms", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            reply = base.feature_roundtrip(dev, FEATURE_ID, build_query(),
                                           FRAME_LEN + 1, wait_ms=20)
            hit = parse(reply) if reply else None
            if hit is None:
                continue
            base.clear_fail(key)
            percent, charging = hit
            name = (ctx.name or "").replace("EWEADN", "").strip()
            return Reading(percent, charging, label="协议包·前行者",
                           model=f"前行者 {name}".strip() or "前行者 S9",
                           kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
