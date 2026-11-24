# -*- coding: utf-8 -*-
"""【手柄】Haute42 Adapter 4DS（格斗手柄 / 方向键盒适配器）

适配设备
    Haute42 Adapter 4DS    054C:0CE6 的适配器形态，USB 有线

怎么读
    只读 feature，零写入。与 DualSense 共用 VID/PID，靠 feature 通道区分：
        get_feature(0xF8) → 以 "Haute42 " 开头的固件串 = 这是适配器
        get_feature(0xF9) → [12] 电量（0xFF = 这一帧没读数）
                            [13] 低 4 位充电（2 = 已充满、非 0 = 充电中、0 = 放电）

注意
    蓝牙路径（{00001124-…}）的是真 DualSense，不归这里 —— 本工具只做 2.4G 与有线。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

SONY_VID = 0x054C
DUALSENSE_PID = 0x0CE6
STATUS_ID = 0xF9
FIRMWARE_ID = 0xF8
PERCENT_INDEX = 12
CHARGE_INDEX = 13
BT_MARK = "{00001124-0000-1000-8000-00805f9b34fb"


def match(ctx: Ctx) -> bool:
    if ctx.vid != SONY_VID or ctx.pid != DUALSENSE_PID:
        return False
    targets = [m for m in ctx.pick(page_=0x0001, usage_=0x0005)
               if BT_MARK not in base.path_text(m).lower()]
    for member in targets:
        if base.feature_length(member) >= 14:
            return True
    return False


def parse_status(raw: bytes):
    """0xF9 状态帧 → (电量 or None, 是否充电)。"""
    if raw is None or len(raw) < 14 or raw[0] != STATUS_ID:
        return None
    if raw[PERCENT_INDEX] == 0xFF:
        return None, None                  # 帧在、但这一帧没带电量
    percent = raw[PERCENT_INDEX]
    if percent > 100:
        return None
    charge = raw[CHARGE_INDEX] & 0x0F
    return percent, charge != 0


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = [m for m in ctx.pick(page_=0x0001, usage_=0x0005)
               if BT_MARK not in base.path_text(m).lower()]
    if not targets:
        return None
    key = ("haute", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            firmware = base.feature_get(dev, FIRMWARE_ID, 64)
            if not firmware or not bytes(firmware[1:]).startswith(b"Haute42 "):
                continue
            status = base.feature_get(dev, STATUS_ID, 64)
            hit = parse_status(bytes(status) if status else b"")
            if hit is None or hit[0] is None:
                continue
            percent, charging = hit
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·Haute42",
                           model="Haute42 Adapter 4DS", kind=base.GAMEPAD,
                           transport="USB 有线")
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
