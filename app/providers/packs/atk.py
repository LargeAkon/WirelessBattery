# -*- coding: utf-8 -*-
"""ATK / VXE：鼠标 17 字节查询帧；键盘走标准 VIA（0xFF60）。

鼠标（0xFF02 接口，17/17，report 0x08）：
    请求 op 帧 = `04` + 14 个 0 + 校验，校验 = (0x4D − op[0..14] 之和) & 0xFF
    应答 op[5] = 电量、op[6] = 充电（0 = 未充电，非 0 = 充电中）、op[7..8] = 电压 mV
    必须校验通过才采信：固件会在同一设备上混发普通鼠标报文，只看命令字会读出假电量。
    覆盖 8K/1K/8K-M/F1 Ultimate/A9 Air/R1 Nearlink 这些接收器，以及有线本体。

键盘（0xFF60，in == out），VIA 自定义通道 0x96 的电量键 0x24：
    请求 `[rid] 02 96 24`
    应答 `02 96 24 <电量> <充电>`
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x373B
MOUSE_PAGE = 0xFF02
VIA_PAGE = 0xFF60
REPORT_ID = 0x08
BATTERY_CMD = 0x04
OP_LEN = 16
FRAME_LEN = 17
SEED = 0x4D
LEVEL_INDEX = 5
CHARGE_INDEX = 6


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if ctx.pick(page_=VIA_PAGE):
        return True
    return bool(_mouse_targets(ctx))


def _mouse_targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.pick(page_=MOUSE_PAGE) if _io_len(m) == FRAME_LEN]


def _io_len(member) -> int:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return 0
    ins = reports.get("in", {}).values()
    outs = reports.get("out", {}).values()
    return min(max(ins, default=0), max(outs, default=0))


def op_checksum(op: bytes) -> int:
    return (SEED - (sum(op[:OP_LEN - 1]) & 0xFF)) & 0xFF


def build_mouse_query() -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[0] = REPORT_ID
    frame[1] = BATTERY_CMD
    frame[FRAME_LEN - 1] = op_checksum(frame[1:])
    return bytes(frame)


def parse_mouse(raw: bytes):
    for off in (1, 0, 2):
        if len(raw) < off + OP_LEN:
            continue
        op = raw[off:off + OP_LEN]
        if op[0] != BATTERY_CMD:
            continue
        if op[OP_LEN - 1] != op_checksum(op):
            continue
        percent = op[LEVEL_INDEX]
        if percent <= 1 or percent > 100:
            return None                     # ≤1 是休眠/关机占位
        charging = op[CHARGE_INDEX] != 0
        return percent, charging
    return None


def build_via_query(length: int) -> bytes:
    frame = bytearray(max(length, 5))
    frame[0] = 0x00
    frame[1] = 0x02
    frame[2] = 0x96
    frame[3] = 0x24
    return bytes(frame)


def parse_via(raw: bytes):
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
    if ctx.pid == 0x10C9:
        return "VXE R1 Nearlink"
    if ctx.pid == 0x10C7:
        return "VXE R1 Nearlink（有线）"
    return f"ATK {name}".strip() if name else "ATK / VXE 无线设备"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    key = ("atk", ctx.phys)
    if base.cooled(key, force):
        return None

    via = ctx.pick(page_=VIA_PAGE)
    if via:
        member = via[0]
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            length = _io_len(member) or 32
            if base.write(dev, build_via_query(length)):
                hit = base.wait_for(dev, parse_via, ms=900, size=max(length, 33))
                if hit is not None:
                    base.clear_fail(key)
                    return Reading(hit[0], hit[1], label="协议包·ATK",
                                   model=_model_name(ctx), kind=base.KEYBOARD,
                                   transport="2.4G 接收器 / USB 有线")
        except Exception:
            pass
        finally:
            base.close(dev)
        base.mark_fail(key)
        return None

    for member in _mouse_targets(ctx)[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, build_mouse_query()):
                continue
            hit = base.wait_for(dev, parse_mouse, ms=1100, size=FRAME_LEN)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·ATK",
                           model=_model_name(ctx), kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
