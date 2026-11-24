# -*- coding: utf-8 -*-
"""【耳机】华硕 ROG 无线耳机（直连 0x1AFA）

适配设备
    ROG 无线耳机     0B05:1AFA，接口 0xFF00/0x0001

怎么认
    直连设备，没有配对表，靠 PID 白名单兜住 —— 这个 PID 下只出现过 ROG 耳机。

怎么读
    `12 07` 取电量、`12 08` 取充电位，两条帧先后等应答，不重试：
        应答 `[0]=0xCC [1]=0x12 [2]=命令 [5..]=载荷`
        电量载荷 [1] 是百分比（0xFE 表示这一帧没读数）

注意
    充电帧没回音时只丢充电位，电量照常显示。
    华硕的键盘（0B05:1ACE，Scope II 96）在 keyboard/asus.py。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x0B05
HEADSET_PID = 0x1AFA

HS_REPORT = 0xCC
GROUP_READ = 0x12
CMD_POWER = 0x07
CMD_CHARGING = 0x08


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != HEADSET_PID:
        return False
    return bool(ctx.pick(page_=0xFF00, usage_=1))


def _query(dev, frame: bytes, matches, ms: int = 700, size: int = 64):
    base.drain(dev)
    if not base.write(dev, frame):
        return None
    return base.wait_for(dev, matches, ms=ms, size=size)


def _frame(report_id: int, command: int, sub: int = 0) -> bytes:
    frame = bytearray(64)
    frame[0] = report_id
    frame[1] = command
    frame[2] = sub
    return bytes(frame)


def _parse_headset(command: int):
    def parse(raw: bytes):
        if len(raw) < 6 or raw[0] != HS_REPORT or raw[1] != GROUP_READ or raw[2] != command:
            return None
        return raw[5:]
    return parse


def _headset_name(ctx: Ctx) -> str:
    name = (ctx.name or "").strip()
    if not name or name.isupper() or name.lower().startswith("usb"):
        return "华硕 ROG 耳机"
    return f"华硕 {name}"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=0xFF00, usage_=1)
    if not targets:
        return None
    key = ("asus-hs", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            data = _query(dev, _frame(HS_REPORT, GROUP_READ, CMD_POWER),
                          _parse_headset(CMD_POWER))
            if data is None or len(data) < 4:
                continue
            percent = data[1]
            if percent == 0xFE or percent > 100:
                continue
            charging_frame = _query(dev, _frame(HS_REPORT, GROUP_READ, CMD_CHARGING),
                                    _parse_headset(CMD_CHARGING))
            charging = None
            if charging_frame:
                charging = charging_frame[0] == 1
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·华硕",
                           model=_headset_name(ctx), kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
