# -*- coding: utf-8 -*-
"""【耳机】狼蛛 AULA G9

适配设备
    AULA G9       38A6:0030，接口 0xFFAB，输入 ≥9 字节

怎么认
    VID:PID + 0xFFAB 厂商页。同号的 L9 Ultra 是鼠标（0xFFA8），在 mouse/aula.py。

怎么读
    纯被动，零写入。每秒一条 `AB 47 4D 86 …`：
        [6] = 电量、[7] = 充电（0x02 充电中）

注意
    旧固件（V0.0.4）电量与标志都恒 0，那是"没在报数"，不是真空电 ——
    这一帧直接判无效，不要显示 0%。
    被动窗口 2.2 秒，听不到就下一轮再试。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x38A6
PID = 0x0030
PAGE = 0xFFAB
MIN_IN = 9
RID = 0xAB
LEVEL_INDEX = 6
CHARGE_INDEX = 7
LISTEN_MS = 2200


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return any(base.io_lengths(m)[0] >= MIN_IN for m in ctx.pick(page_=PAGE))


def parse(raw: bytes):
    if len(raw) <= CHARGE_INDEX:
        return None
    if raw[0] != RID or raw[1] != 0x47 or raw[2] != 0x4D or raw[3] != 0x86:
        return None
    level = raw[LEVEL_INDEX]
    if level > 100:
        return None
    flag = raw[CHARGE_INDEX]
    if level == 0 and flag == 0:
        return None                          # 旧固件不报数
    return level, flag == 0x02


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = [m for m in ctx.pick(page_=PAGE)
               if base.io_lengths(m)[0] >= MIN_IN]
    if not targets:
        return None
    key = ("aula-g9", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = base.wait_for(dev, parse, ms=LISTEN_MS)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·狼蛛",
                           model="狼蛛 G9", kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
