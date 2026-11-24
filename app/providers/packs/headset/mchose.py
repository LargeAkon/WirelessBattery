# -*- coding: utf-8 -*-
"""【耳机】迈从 MCHOSE V9 Pro、X9

适配设备
    迈从 V9 Pro     291D:385D，接口 0xFF90/0x0001，64/64，col05 集合
    迈从 X9         3837:6045，同结构；VID 与迈从键鼠同号段，
                    所以必须靠 col05 接口 + PID 认，不能按 VID 认

怎么认
    两条都要求接口路径里带 `&mi_00&col05#`（麦克风那一组 collection），
    这是迈从耳机的固定形态。

怎么读
    查询 `55 65 01`，应答 [1]=0x65、[2]=电量。
    X9 的 [3] 是充电状态：2 放电 / 3 充电 / 4 充满 / 0x1A 休眠。
    V9 Pro 没有充电位，只报电量（不猜）。

注意
    有的接收器会把查询原样回显成"1% 应答"，整帧等于查询帧时直接丢弃。
    迈从的键盘在 keyboard/mchose.py，鼠标在 mouse/mchose.py。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3837
VID_LEGACY = 0x41E4
V9_VID = 0x291D
V9_PID = 0x385D
X9_PID = 0x6045

HS_RID = 0x55
HS_ECHO = 0x65
HS_LEN = 64


def _is_headset_path(member) -> bool:
    return "&mi_00&col05#" in base.path_text(member).lower()


def kind_of(ctx: Ctx) -> str | None:
    if ctx.vid == V9_VID and ctx.pid == V9_PID:
        return "v9" if any(_is_headset_path(m) for m in ctx.members) else None
    if ctx.vid not in (VID, VID_LEGACY):
        return None
    if ctx.pid == X9_PID:
        return "x9" if any(_is_headset_path(m) for m in ctx.members) else None
    return None


def match(ctx: Ctx) -> bool:
    return kind_of(ctx) is not None


def _targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.members if _is_headset_path(m)]


def hs_query() -> bytes:
    frame = bytearray(HS_LEN)
    frame[0] = HS_RID
    frame[1] = HS_ECHO
    frame[2] = 0x01
    return bytes(frame)


def hs_parse(raw: bytes, with_status: bool):
    if raw is None or len(raw) != HS_LEN:
        return None
    if raw[0] != HS_RID or raw[1] != HS_ECHO:
        return None
    percent = raw[2]
    if percent == 0 or percent > 100:
        return None
    if bytes(raw) == hs_query():
        return None                          # 主机写入被回显
    if not with_status:
        return percent, None
    status = raw[3]
    if status in (0x02, 0x1A):
        return percent, False
    if status == 0x03:
        return percent, True
    if status == 0x04:
        return percent, False
    return percent, None


def _hs_probe(dev, with_status: bool):
    base.drain(dev)
    if not base.write(dev, hs_query()):
        return None
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        raw = base.read(dev, 200, HS_LEN)
        if raw is None:
            continue
        hit = hs_parse(raw, with_status)
        if hit is not None:
            return hit
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    kind = kind_of(ctx)
    if kind is None:
        return None
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("mchose-headset", kind, ctx.phys)
    if base.cooled(key, force):
        return None

    model = "迈从 V9 Pro" if kind == "v9" else "迈从 X9"
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = _hs_probe(dev, with_status=(kind == "x9"))
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·迈从",
                           model=model, kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
