# -*- coding: utf-8 -*-
"""【鼠标】迈从 MCHOSE A5 V2 Ultra、G3 V2、V2 系列

适配设备
    迈从 A5 V2 Ultra    3837:100C，接口 0xFF01/0x0001，feature ≥21
    迈从 G3 V2          3837:4245，接口 0xFF01/0x0010，65/65
    迈从 鼠标 V2 系列    3837 / 41E4，厂商页且输入输出都 ≥60（G87 V2 / A7 V2 Pro 等）

怎么认
    判据是完整接口指纹，不做"同 VID 就试试"。
    已属于键盘的 3837:1018（K7）与属于耳机的 3837:6045（X9）在这里一律不碰，
    它们分别由 keyboard/mchose.py、headset/mchose.py 负责。

怎么读
    A5 V2 Ultra（反码 Feature 0x11）：
        SetFeature(0x11, `F9` + 19 个 0xFF) → 等输入通知（`13 xx F9`）→ GetFeature(0x11)
        应答 [2..3]/[4..5] 是鼠标本体 VID/PID（取反），[11] 电量、[12] 充电（取反）
        —— 这一段取反是设备固件的行为，不是笔误。
    G3 V2：
        查询 `00 55 30 A5 0B 2E 01 01 01`；应答 AA 30 前缀，[off+8] 电量、[off+9] 充电。
    鼠标 V2：
        接收器自发 E2 状态帧（整帧逐字节取反：[0]=0xE2、[3]=充电、[4]=电量）。
        先纯被动等 3 秒；等不到才发一次触发帧 `11 F9 FF…`（官方 MOUSE_LEGACY 同款），
        再等 3 秒。E2 帧是接收器自发流，主动查询只会干扰鼠标。

注意
    迈从的键盘在 keyboard/mchose.py，耳机在 headset/mchose.py。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3837
VID_LEGACY = 0x41E4
A5_PID = 0x100C
K7_PID = 0x1018
GMOUSE_PID = 0x4245
X9_PID = 0x6045

V2_STATUS = 0xE2
V2_POKE_RID = 0x11
V2_POKE_CMD = 0x06


def kind_of(ctx: Ctx) -> str | None:
    """本目录负责的三条链路：'a5' / 'gmouse' / 'mouse'；其余返回 None。"""
    if ctx.vid not in (VID, VID_LEGACY):
        return None

    if ctx.pid == A5_PID:
        if not ctx.pick(page_=0xFF01, usage_=0x0001):
            return None
        return "a5" if any(base.feature_length(m) >= 21 for m in ctx.members) else None

    if ctx.pid == GMOUSE_PID:
        return "gmouse" if ctx.pick(page_=0xFF01, usage_=0x0010) else None

    # 这两个号段属于键盘与耳机，交给各自目录，避免鼠标分支抢应答帧
    if ctx.pid in (K7_PID, X9_PID):
        return None

    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        ins, outs = base.io_lengths(member)
        if ins >= 60 and outs >= 60:
            return "mouse"
    return None


def match(ctx: Ctx) -> bool:
    return kind_of(ctx) is not None


def _targets(ctx: Ctx, kind: str) -> list[dict]:
    if kind == "a5":
        return ctx.pick(page_=0xFF01, usage_=0x0001)
    if kind == "gmouse":
        return ctx.pick(page_=0xFF01, usage_=0x0010)
    return [m for m in ctx.members
            if base.io_lengths(m)[0] >= 60 and base.io_lengths(m)[1] >= 60]


# ---------------- 鼠标 V2 ----------------
def v2_parse(raw: bytes):
    for off in (1, 0):
        if len(raw) < off + 5:
            continue
        lo = bytes(byte ^ 0xFF for byte in raw[off:])
        if lo[0] != V2_STATUS:
            continue
        percent = lo[4]
        if percent == 0 or percent > 100:
            return None
        return percent, lo[3] == 1
    return None


def v2_poke(length: int) -> bytes:
    frame = bytearray(max(length, 2))
    frame[0] = V2_POKE_RID
    frame[1] = V2_POKE_CMD ^ 0xFF
    for i in range(2, len(frame)):
        frame[i] = 0xFF
    return bytes(frame)


def _mouse_probe(dev, length: int):
    hit = base.wait_for(dev, v2_parse, ms=1200)
    if hit is not None:
        return hit
    if not base.write(dev, v2_poke(length)):
        return None
    return base.wait_for(dev, v2_parse, ms=1400)


# ---------------- Gmouse ----------------
def gmouse_query() -> bytes:
    frame = bytearray(65)
    frame[1:9] = bytes([0x55, 0x30, 0xA5, 0x0B, 0x2E, 0x01, 0x01, 0x01])
    return bytes(frame)


def gmouse_parse(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 10:
            continue
        if raw[off] != 0xAA or raw[off + 1] != 0x30:
            continue
        percent = raw[off + 8]
        if percent < 1 or percent > 100:
            return None
        return percent, raw[off + 9] != 0
    return None


# ---------------- A5 V2 Ultra ----------------
def a5_payload() -> bytes:
    return bytes([0xF9]) + bytes([0xFF] * 19)


def a5_notification(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0] == 0x13 and raw[2] == 0xF9


def a5_parse(raw):
    if raw is None or len(raw) < 21 or raw[0] != 0x11 or raw[1] != 0xF9:
        return None
    vid = (raw[2] ^ 0xFF) | ((raw[3] ^ 0xFF) << 8)
    pid = (raw[4] ^ 0xFF) | ((raw[5] ^ 0xFF) << 8)
    if vid != 0x41E4 or pid not in (0x1101, 0x1102):
        return None
    level = raw[11] ^ 0xFF
    charge = raw[12] ^ 0xFF
    if level > 100 or charge > 2:
        return None
    return level, (None if charge == 2 else charge == 1)


def _a5_probe(dev):
    try:
        dev.send_feature_report(bytes([0x11]) + a5_payload())
    except Exception:
        return None
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        raw = base.read(dev, 100, 21)
        if raw is None or not a5_notification(raw):
            continue
        reply = base.feature_get(dev, 0x11, 21)
        return a5_parse(reply)
    return None


# ---------------- 入口 ----------------
def _model(ctx: Ctx, kind: str) -> str:
    if kind == "a5":
        return "迈从 A5 V2 Ultra"
    if kind == "gmouse":
        return "迈从 G3 V2"
    name = ctx.name or ""
    for word in ("MCHOSE", "2.4G", "Wireless", "Dongle", "Receiver"):
        name = name.replace(word, "")
    name = name.strip(" -_")
    return f"迈从 {name}".strip() if name else f"迈从 ({ctx.vid_pid})"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    kind = kind_of(ctx)
    if kind is None:
        return None
    targets = _targets(ctx, kind)
    if not targets:
        return None
    key = ("mchose-mouse", kind, ctx.phys)
    if base.cooled(key, force):
        return None

    model = _model(ctx, kind)
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            if kind == "a5":
                hit = _a5_probe(dev)
            elif kind == "gmouse":
                base.drain(dev)
                hit = None
                if base.write(dev, gmouse_query()):
                    hit = base.wait_for(dev, gmouse_parse, ms=1100, size=65)
            else:
                hit = _mouse_probe(dev, max(base.io_lengths(member)[1], 64))
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·迈从",
                           model=model, kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
