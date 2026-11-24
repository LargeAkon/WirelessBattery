# -*- coding: utf-8 -*-
"""【鼠标】ATK / VXE 系列无线鼠标

适配设备
    VXE R1 Nearlink         373B:10C9 接收器
    VXE R1 Nearlink（有线）  373B:10C7
    ATK 8K / 1K / 8K-M      373B 同系列接收器，型号名按产品名显示
    ATK F1 Ultimate         同上
    ATK A9 Air              同上
    同系列的其他型号只要走 0xFF02 / 17 字节，一般也能直接读。

怎么认
    接口 0xFF02，输入与输出都是 17 字节，report 0x08。

怎么读
    请求 op 帧 = `04` + 14 个 0 + 校验，校验 = (0x4D − op[0..14] 之和) & 0xFF
    应答 op[5] = 电量、op[6] = 充电（0 未充电，非 0 充电中）、op[7..8] = 电压 mV

注意
    必须校验通过才采信：固件会在同一设备上混发普通鼠标报文，只看命令字
    会读出假电量。电量 ≤1 是休眠/关机占位，判无效。
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
    # 带 VIA 通道（0xFF60）的一律交给 keyboard/atk：原实现里键盘优先，
    # 键盘读失败也不再回头试鼠标链路，这里保持同样的优先级。
    if ctx.pick(page_=VIA_PAGE):
        return False
    return bool(_targets(ctx))


def _targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.pick(page_=MOUSE_PAGE)
            if min(base.io_lengths(m)) == FRAME_LEN]


def op_checksum(op: bytes) -> int:
    return (SEED - (sum(op[:OP_LEN - 1]) & 0xFF)) & 0xFF


def build_query() -> bytes:
    frame = bytearray(FRAME_LEN)
    frame[0] = REPORT_ID
    frame[1] = BATTERY_CMD
    frame[FRAME_LEN - 1] = op_checksum(frame[1:])
    return bytes(frame)


def parse(raw: bytes):
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


def _model_name(ctx: Ctx) -> str:
    if ctx.pid == 0x10C9:
        return "VXE R1 Nearlink"
    if ctx.pid == 0x10C7:
        return "VXE R1 Nearlink（有线）"
    name = (ctx.name or "").replace("ATK", "").replace("Wireless", "").strip()
    return f"ATK {name}".strip() if name else "ATK / VXE 无线鼠标"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("atk-mouse", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, build_query()):
                continue
            hit = base.wait_for(dev, parse, ms=1100, size=FRAME_LEN)
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
