# -*- coding: utf-8 -*-
"""前行者 EWEADN：X87 键盘（0C45:FEFE）与 S9 鼠标（372E:1026）。

X87 走 33 字节输出帧：`00 20 01 …校验`，校验是全部字节求和取低 8 位，
放在 [32]。官方驱动把充电位固定传 0，这里跟着官方走。

S9 是邮箱式 feature：先写 63 字节 BASICS 查询（0x4F/0x81，CRC 在
payload[0]），等 20ms 再读同一个 feature，电量在应答 [6]，bit7 是充电。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

KB_VID = 0x0C45
KB_PID = 0xFEFE
KB_PAGE = 0xFF60
KB_USAGE = 0x0061
KB_FRAME = 33

MS_VID = 0x372E
MS_PID = 0x1026
MS_PAGE = 0xFF00
MS_USAGE = 0x0001
MS_FEATURE_ID = 0x03
MS_FRAME = 63


def match(ctx: Ctx) -> bool:
    if ctx.vid == KB_VID and ctx.pid == KB_PID:
        return bool(ctx.pick(page_=KB_PAGE, usage_=KB_USAGE))
    if ctx.vid == MS_VID and ctx.pid == MS_PID:
        return bool(ctx.pick(page_=MS_PAGE, usage_=MS_USAGE))
    return False


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    if ctx.vid == KB_VID:
        return _keyboard(ctx, force)
    return _mouse(ctx, force)


# ---------------- X87 键盘 ----------------
def keyboard_query() -> bytes:
    frame = bytearray(KB_FRAME)
    frame[1] = 0x20
    frame[2] = 0x01
    frame[KB_FRAME - 1] = sum(frame) & 0xFF
    return bytes(frame)


def parse_keyboard(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 4:
            continue
        if raw[off] != 0x20 or raw[off + 1] != 0x01:
            continue
        percent = raw[off + 3]
        if percent == 0:            # 0 = 设备未就绪，不是电量
            return None
        return min(100, percent)
    return None


def _keyboard(ctx: Ctx, force: bool) -> Reading | None:
    targets = ctx.pick(page_=KB_PAGE, usage_=KB_USAGE)
    if not targets:
        return None
    key = ("eweadn-kb", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, keyboard_query()):
                continue
            percent = base.wait_for(dev, parse_keyboard, ms=1500)
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, None, label="协议包·前行者",
                           model="前行者 X87", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None


# ---------------- S9 鼠标 ----------------
def mouse_query() -> bytes:
    frame = bytearray(MS_FRAME)
    frame[1] = 0x50
    frame[2] = 0x00
    frame[3] = 0x02
    frame[4] = 0x4F
    frame[5] = 0x81
    frame[0] = sum(frame[1:]) & 0xFF     # CRC 从下标 1 起算
    return bytes(frame)


def parse_mouse(raw: bytes):
    if len(raw) < 7:
        return None
    if raw[0] != MS_FEATURE_ID or raw[1] != 0x50:
        return None
    value = raw[6]
    percent = value & 0x7F
    if percent == 0 or percent > 100:     # 休眠时回结构合法的 0
        return None
    return percent, (value & 0x80) != 0


def _mouse(ctx: Ctx, force: bool) -> Reading | None:
    targets = ctx.pick(page_=MS_PAGE, usage_=MS_USAGE)
    if not targets:
        return None
    key = ("eweadn-ms", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            reply = base.feature_roundtrip(dev, MS_FEATURE_ID, mouse_query(),
                                           MS_FRAME + 1, wait_ms=20)
            hit = parse_mouse(reply) if reply else None
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
