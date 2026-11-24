# -*- coding: utf-8 -*-
"""墨将（MOJHON）烈风2 GALE2：E2B7:122C，A5 帧协议读电量寄存器。

帧格式（USBPcap 实录，35/35 帧校验通过）：
    [0xA5 短帧] [总长度（含头尾）] [寄存器] [载荷…] [校验]
    校验 = 除末字节外全部字节之和 & 0xFF
读请求恒为 4 字节 `A5 04 <寄存器> <校验>`；设备回复时原样回显寄存器号。

电量寄存器 0x04：payload[0] = 百分比、payload[1] = 充电标志（0 放电 / 1 充电）。

两个坑：
1. 描述符声明 64/64 且无 Report ID，但 Windows 报 OutputReportLength = 65，
   必须写 65 字节、帧从下标 1 起（[0] 固定 0x00）才拿得到应答。
2. 同一接口上会有上一轮迟到的其他寄存器应答，只认寄存器号对得上的那条。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0xE2B7
USAGE_PAGE = 0xFFAB
REGISTER_BATTERY = 0x04
REGISTER_NAME = 0xE2


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if not (ctx.pick(page_=USAGE_PAGE) or ctx.pick(usage_=USAGE_PAGE)):
        return False
    return any(_len_ok(m) for m in ctx.members)


def _len_ok(member) -> bool:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return False
    return any(v >= 64 for v in reports.get("out", {}).values()) and \
        any(v >= 64 for v in reports.get("in", {}).values())


def checksum(head: bytes) -> int:
    return sum(head) & 0xFF


def build_read(register: int) -> bytes:
    frame = bytearray(64)
    frame[0] = 0xA5
    frame[1] = 4
    frame[2] = register
    frame[3] = checksum(frame[:3])
    return bytes(frame)


def parse_frame(raw: bytes):
    """返回 (寄存器, 载荷) 或 None。"""
    if len(raw) < 4:
        return None
    offset = 0 if raw[0] in (0xA5, 0xA4) else (1 if len(raw) > 1 and raw[1] in (0xA5, 0xA4) else -1)
    if offset < 0:
        return None
    length = raw[offset + 1]
    if length < 4 or offset + length > len(raw):
        return None
    body = raw[offset:offset + length]
    if checksum(body[:-1]) != body[-1]:
        return None
    return body[2], body[3:-1]


def parse_reply(raw: bytes):
    hit = parse_frame(raw)
    if hit is None:
        return None
    register, payload = hit
    if register != REGISTER_BATTERY or not payload:
        return None
    percent = payload[0]
    if percent > 100:
        return None
    charging = payload[1] == 1 if len(payload) >= 2 else None
    return percent, charging


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=USAGE_PAGE) or ctx.pick(usage_=USAGE_PAGE)
    if not targets:
        return None
    key = ("mojhon", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            frame = build_read(REGISTER_BATTERY)
            # Windows 的报文长度比描述符多 1 字节，那一字节是填充，不是 report ID
            padding = 1 if len(frame) < 65 else 0
            if not base.write(dev, (b"\x00" * padding) + frame):
                continue
            hit = base.wait_for(dev, parse_reply, ms=1100, size=65)
            if hit is None:
                continue
            percent, charging = hit
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·墨将",
                           model="墨将 烈风2 GALE2", kind=base.GAMEPAD,
                           transport="2.4G 接收器 / 有线")
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
