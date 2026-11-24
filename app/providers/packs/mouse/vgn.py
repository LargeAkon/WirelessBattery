# -*- coding: utf-8 -*-
"""【鼠标】VGN 蜻蜓 F1 V5 Turbo+、蜻蜓 F2 大师+

适配设备
    VGN 蜻蜓 F1 V5 Turbo+    391D:1A23 接收器 · 391D:1026 有线本体
    VGN 蜻蜓 F2 大师+        3554:FB56 接收器 · 3554:FB57 有线本体

怎么认
    kc2：接口 0xFFC1/0x0001，输入输出都 ≥64 字节。
    y2 ：接口 0xFF02/0x0002，输入输出**恰好** 17/17 字节。
         长度必须精确相等：同 VID 下狼蛛 F99 Pro 是 20/20，放宽会把 17 字节帧
         灌进 20 字节通道。

怎么读
    kc2：请求 `B3 06` + 62 个 0；应答 payload[0]=0x06，
         电量在 payload[19]（bit7 = 充电、低 7 位 = 百分比）。
         门槛：payload 里至少 3 个非零字节才认，挡掉"读失败返回全零缓冲"。
    y2 ：请求 `08 04`，校验 = (85 − 前 15 字节之和 − reportId) & 0xFF
         应答 payload[5] = 电量（0 与 >100 都判无效）、[6] = 充电、[7..8] = 电压 mV

注意
    VGN 的键盘 V98 Pro 在 keyboard/vgn.py；320F:5088 那个号段上还有
    VXE75 走 Evision 芯片通道，那边有产品名让位逻辑。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

# kc2
KC2_VID = 0x391D
KC2_PIDS = (0x1A23, 0x1026)
KC2_PAGE = 0xFFC1
KC2_USAGE = 0x0001
KC2_RID = 0xB3
KC2_CMD = 0x06
KC2_LEN = 64
KC2_LEVEL = 19
KC2_CHARGE_BIT = 0x80

# y2
Y2_VID = 0x3554
Y2_PIDS = (0xFB56, 0xFB57)
Y2_PAGE = 0xFF02
Y2_USAGE = 0x0002
Y2_RID = 0x08
Y2_CMD = 0x04
Y2_PAYLOAD = 16
Y2_LEN = 17
Y2_SEED = 85


def match(ctx: Ctx) -> bool:
    return _is_kc2(ctx) or _is_y2(ctx)


def _is_kc2(ctx: Ctx) -> bool:
    if ctx.vid != KC2_VID or ctx.pid not in KC2_PIDS:
        return False
    targets = ctx.pick(page_=KC2_PAGE, usage_=KC2_USAGE)
    return any(min(base.io_lengths(m)) >= KC2_LEN for m in targets)


def _is_y2(ctx: Ctx) -> bool:
    if ctx.vid != Y2_VID or ctx.pid not in Y2_PIDS:
        return False
    targets = ctx.pick(page_=Y2_PAGE, usage_=Y2_USAGE)
    return any(base.io_lengths(m) == (Y2_LEN, Y2_LEN) for m in targets)


# ---------------- kc2 ----------------
def build_kc2() -> bytes:
    frame = bytearray(KC2_LEN)
    frame[0] = KC2_RID
    frame[1] = KC2_CMD
    return bytes(frame)


def parse_kc2(raw: bytes):
    for start in (1, 0):
        if len(raw) < start + KC2_LEVEL + 1:
            continue
        if raw[start] != KC2_CMD:
            continue
        non_zero = sum(1 for byte in raw[start + 1:start + 41] if byte)
        if non_zero < 3:
            continue                        # 全零缓冲 = 没读到
        packed = raw[start + KC2_LEVEL]
        percent = packed & 0x7F
        if percent > 100:
            continue
        charging = bool(packed & KC2_CHARGE_BIT)
        return percent, charging
    return None


# ---------------- y2 ----------------
def y2_checksum(payload: bytes, report_id: int = Y2_RID) -> int:
    return (Y2_SEED - (sum(payload[:Y2_PAYLOAD - 1]) & 0xFF) - report_id) & 0xFF


def build_y2() -> bytes:
    frame = bytearray(Y2_LEN)
    frame[0] = Y2_RID
    frame[1] = Y2_CMD
    frame[-1] = y2_checksum(frame[1:])
    return bytes(frame)


def parse_y2(raw: bytes):
    starts = (1, 0) if len(raw) >= Y2_LEN and raw[0] == Y2_RID else (0,)
    for start in starts:
        if len(raw) < start + Y2_PAYLOAD:
            continue
        payload = raw[start:start + Y2_PAYLOAD]
        if payload[0] != Y2_CMD or payload[1] != 0:
            continue
        if payload[-1] != y2_checksum(payload):
            continue
        percent = payload[5]
        if percent == 0 or percent > 100:
            continue
        return percent, payload[6] == 1
    return None


def _model(ctx: Ctx) -> str:
    if _is_y2(ctx):
        return "VGN 蜻蜓 F2 大师+"
    return "VGN 蜻蜓 F1 V5 Turbo+"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    key = ("vgn-mouse", ctx.phys)
    if base.cooled(key, force):
        return None

    if _is_y2(ctx):
        plan = [(m, "y2") for m in ctx.pick(page_=Y2_PAGE, usage_=Y2_USAGE)]
    elif _is_kc2(ctx):
        plan = [(m, "kc2") for m in ctx.pick(page_=KC2_PAGE, usage_=KC2_USAGE)]
    else:
        plan = []

    for member, kind in plan[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if kind == "y2":
                if not base.write(dev, build_y2()):
                    continue
                hit = base.wait_for(dev, parse_y2, ms=900, size=Y2_LEN)
            else:
                if not base.write(dev, build_kc2()):
                    continue
                hit = base.wait_for(dev, parse_kc2, ms=900, size=KC2_LEN)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·VGN",
                           model=_model(ctx), kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
