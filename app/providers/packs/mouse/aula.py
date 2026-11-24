# -*- coding: utf-8 -*-
"""【鼠标】狼蛛 AULA L9 Ultra

适配设备
    AULA L9 Ultra     38A6:28FD，接口 0xFFA8

怎么认
    VID:PID + 0xFFA8 输入 ≥11、输出 ≥3 的接口。同号的 G9 是耳机（0xFFAB），
    在 headset/aula.py。

怎么读
    发一条 `0B 81` 查询，回包 `0A 81 …`：
        [18] = 电量、[17] = 充电（非 0 充电中）

注意
    查询长度按接口声明的输出长度写满，写短了设备不回应。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x38A6
PID = 0x28FD
PAGE = 0xFFA8
MIN_IN = 11
MIN_OUT = 3
OUT_ID = 0x0B
IN_ID = 0x0A
CMD = 0x81
CHARGE_INDEX = 17
LEVEL_INDEX = 18


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(_targets(ctx))


def _targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.pick(page_=PAGE)
            if base.io_lengths(m)[0] >= MIN_IN and base.io_lengths(m)[1] >= MIN_OUT]


def build_query(length: int) -> bytes:
    frame = bytearray(max(length, 3))
    frame[0] = OUT_ID
    frame[1] = CMD
    return bytes(frame)


def parse(raw: bytes):
    if len(raw) <= LEVEL_INDEX:
        return None
    if raw[0] != IN_ID or raw[1] != CMD:
        return None
    level = raw[LEVEL_INDEX]
    if level > 100:
        return None
    return level, raw[CHARGE_INDEX] != 0


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("aula-l9", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, build_query(base.io_lengths(member)[1])):
                continue
            hit = base.wait_for(dev, parse, ms=1300)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·狼蛛",
                           model="狼蛛 L9 Ultra", kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
