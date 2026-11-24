# -*- coding: utf-8 -*-
"""雷柏 VT3 二代：被动 report 0x07 状态帧（19 字节），零写入。

帧布局：
    [0]   = 0x07
    [1]低4位 = 连接方式（0 = 2.4G、2 = 有线）
    [7]   = 充电标志（0x01 放电 / 0x02 充电 / 0x00 切换瞬间）
    [8]   = 电量
    [18].bit7 = 1 表示 RF 链路在线（只在 2.4G 模式下有意义）

心跳约 3 秒一条，所以被动窗口取 5 秒；听不到就是鼠标在睡，这一轮不认领。
满电优先判「充满」：满电放底座时 [7] 会在 0/1/2 之间横跳，先判 0x02 会让图标连闪。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x24AE
REPORT_ID = 0x07
REPORT_LEN = 19
CHARGE_INDEX = 7
PERCENT_INDEX = 8
RF_INDEX = 18
LINK_MASK = 0x0F
LINK_WIRED = 2

_LISTEN_MS = 5200


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    targets = ctx.pick(page_=0xFF00) or ctx.pick(usage_=0xFF00)
    # 状态帧走 19 字节输入报告；同接收器上的 8 字节键盘集合不认
    return any(_long_enough(m) for m in targets)


def _long_enough(member) -> bool:
    from providers import hidreports
    try:
        inputs = hidreports.reports(member.get("path")).get("in", {})
    except Exception:
        return False
    return any(length >= REPORT_LEN for length in inputs.values())


def parse(raw: bytes):
    """返回 (电量, 是否充电, 链路是否在线) 或 None。"""
    for off in (0, 1):
        if len(raw) < off + REPORT_LEN:
            continue
        if raw[off] != REPORT_ID:
            continue
        percent = raw[off + PERCENT_INDEX]
        if percent == 0 or percent > 100:
            return None                       # 休眠瞬态，读数不可用
        mode = raw[off + 1] & LINK_MASK
        rf_byte = raw[off + RF_INDEX]
        linked = (rf_byte & 0x80) != 0 or mode == LINK_WIRED
        charging = percent >= 100 or raw[off + CHARGE_INDEX] == 0x02
        return percent, charging, linked
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=0xFF00) or ctx.pick(usage_=0xFF00)
    if not targets:
        return None
    key = ("rapoo", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = base.wait_for(dev, parse, ms=_LISTEN_MS)
            if hit is None:
                continue
            percent, charging, linked = hit
            if not linked:
                continue                      # dongle 在位但鼠标没连上
            base.clear_fail(key)
            name = (ctx.name or "").replace("Rapoo", "").strip()
            model = f"雷柏 {name}".strip() if name else "雷柏"
            return Reading(percent, charging, label="协议包·雷柏",
                           model=model, kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
