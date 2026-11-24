# -*- coding: utf-8 -*-
"""GANSS GS3104T-Pro / 狼蛛 F108 Pro：05AC:024F，33 字节查询帧。

两家在 HID 层完全同指纹（同硅方案），只能靠产品名区分（GANSS / GS3104 / F108），
接口编号 &mi_03# 作为补充证据。

查询：33 字节，[1]=0x20  [2]=0x01  [32]=0x21（其余 0）
应答：33 字节，[0] 是 report ID（0），剥掉后 32 字节：
    [0]=0x20  [1]=0x01  [2]=0  [3]=电量  [31]=前 31 字节之和
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x05AC
PID = 0x024F
PAGE = 0xFF60
USAGE = 0x0061
REPORT_LEN = 33
PERCENT_INDEX = 3


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    if not ctx.pick(page_=PAGE, usage_=USAGE):
        return False
    name = (ctx.name or "").lower()
    by_name = "ganss" in name or "gs3104" in name or "f108" in name
    by_path = any("&mi_03#" in base.path_text(m).lower() for m in ctx.members)
    return by_name or by_path


def query_frame() -> bytes:
    frame = bytearray(REPORT_LEN)
    frame[1] = 0x20
    frame[2] = 0x01
    frame[-1] = 0x21
    return bytes(frame)


def parse(raw: bytes):
    if len(raw) == REPORT_LEN:
        if raw[0] != 0:
            return None
        raw = raw[1:]
    if len(raw) != REPORT_LEN - 1:
        return None
    if raw[0] != 0x20 or raw[1] != 0x01 or raw[2] != 0:
        return None
    percent = raw[PERCENT_INDEX]
    if percent == 0 or percent > 100:
        return None
    if (sum(raw[:-1]) & 0xFF) != raw[-1]:
        return None
    return percent


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("ganss", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, query_frame()):
                continue
            percent = base.wait_for(dev, parse, ms=900, size=REPORT_LEN)
            if percent is None:
                continue
            base.clear_fail(key)
            name = ctx.name or ""
            if "108" in name:
                model = "狼蛛 F108 Pro"
            elif "GS3104" in name.upper():
                model = "GANSS GS3104T-Pro"
            else:
                model = "GANSS GS3104T-Pro"
            return Reading(percent, None, label="协议包·GANSS",
                           model=model, kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
