# -*- coding: utf-8 -*-
"""北通 BETOP：T9 手柄（被动状态流）与鲲鹏20/70（广播 + 有线查询）。

判据：VID 0x20BC（旧接收器）或 0x20DD（新批次 dongle），且 usage page / usage
含 0xFF00（厂商页，须查询）或 0x00FF（杂项广播页，每秒自推）。

T9 状态流（Col04，report 0x04，≥24 字节，不响应查询）：
    [23] = 原始电量，编码是「4 位电量档 × 8」，满值 120
    0x50 是 dongle "手柄未连接" 的占位值 —— 不是电量，这一帧要当作离线
    识别只能看 report ID：[1] 是可变状态位（实测 0x02/0x04/0x0C）

状态报告（report 0x02，[1] = 0x15 = sub 0x1 << 4 | cmd 0x5）：
    [2] = 电量  [4] 低 4 位 = 充电标志（非 0 充电中）
    有线/静默时发 `02 15 00…` 查询，长度必须写满接口声明的输出长度。

先被动听 1.2 秒（T9 与鲲鹏都在推），听不到再发一条查询。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID_OLD = 0x20BC
VID_NEW = 0x20DD
VENDOR_PAGE = 0xFF00
BROADCAST_PAGE = 0x00FF

STATUS_RID = 0x02
STATUS_HEADER = 0x15
BATTERY_INDEX = 2
CHARGE_INDEX = 4
CHARGE_MASK = 0x0F

T9_RID = 0x04
T9_MIN_LEN = 24
T9_BATTERY_INDEX = 23
T9_FULL = 120
T9_NOT_LINKED = 0x50


def _is_betop_page(value: int) -> bool:
    return value in (VENDOR_PAGE, BROADCAST_PAGE)


def match(ctx: Ctx) -> bool:
    if ctx.vid not in (VID_OLD, VID_NEW):
        return False
    return any(_is_betop_page(base.page(m)) or _is_betop_page(base.usage(m))
               for m in ctx.members)


def _targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.members
            if _is_betop_page(base.page(m)) or _is_betop_page(base.usage(m))]


def parse_t9(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + T9_MIN_LEN:
            continue
        if raw[off] != T9_RID:
            continue
        value = raw[off + T9_BATTERY_INDEX]
        if value == 0 or value > T9_FULL:
            return None
        if value == T9_NOT_LINKED:
            return None                     # dongle 占位帧：手柄没连上
        percent = (value * 100 + T9_FULL // 2) // T9_FULL
        return percent, False
    return None


def parse_status(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + CHARGE_INDEX + 1:
            continue
        if raw[off] != STATUS_RID or raw[off + 1] != STATUS_HEADER:
            continue
        percent = raw[off + BATTERY_INDEX]
        if percent == 0 or percent > 100:
            return None
        return percent, (raw[off + CHARGE_INDEX] & CHARGE_MASK) != 0
    return None


def parse_any(raw: bytes):
    return parse_status(raw) or parse_t9(raw)


def build_query(length: int) -> bytes:
    frame = bytearray(max(length, 2))
    frame[0] = STATUS_RID
    frame[1] = STATUS_HEADER
    return bytes(frame)


def _out_len(member) -> int:
    from providers import hidreports
    try:
        outs = hidreports.reports(member.get("path")).get("out", {})
    except Exception:
        return 0
    return max(outs.values()) if outs else 0


def _model(ctx: Ctx) -> str:
    text = (ctx.name or "").upper()
    for brand in ("BEITONG", "BETOP", "北通"):
        if text.startswith(brand):
            text = text[len(brand):].lstrip(" -_:：")
            break
    if " FOR " in text:
        text = text.split(" FOR ")[0]
    text = text.strip()
    return f"北通 {text}".strip() if text else "北通手柄"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("betop", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = base.wait_for(dev, parse_any, ms=1200)
            if hit is None:
                length = _out_len(member)
                if length >= 2 and base.write(dev, build_query(length)):
                    hit = base.wait_for(dev, parse_any, ms=1000)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·北通",
                           model=_model(ctx), kind=base.GAMEPAD,
                           transport="2.4G 接收器 / USB 有线")
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
