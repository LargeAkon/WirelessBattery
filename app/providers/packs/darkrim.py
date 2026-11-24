# -*- coding: utf-8 -*-
"""寸渊影弑 SHADOW（杰理 dongle）：3654:6901，帧头 0xFE + CRC-16/CCITT-FALSE。

dongle 不会主动推电量（纯听 45 秒、重插、重开句柄都拿不到），必须发官方同款的
GetBasicInfo 只读查询 `fe 00 10 00 02 00 00 03 00 09 01 00 e2 3c`，立刻回 0x11/01 电量帧。

帧结构：
    [0]=0xFE [1]=seq [2]=cmd（0x10 主机→dongle / 0x11 上报） [3]=方向 [4]=来源
    [5]=块号 [6]=块数 [7]=载荷长 [8]=块标志 [9..]=载荷 [CRC16 大端]
电量载荷：`01 <数据长度> <数据…>`，每个数据字节 bit7 = 充电中、低 7 位 = 百分比；
双耳取较低的那只，只有充电盒读数时用充电盒。

两个坑：接口会把写出去的帧原样读回（cmd=0x10），必须跳过；hidapi 会把 report ID 剥掉，
所以帧头可能在 [0] 或 [1]。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3654
PID = 0x6901
PAGE = 0xFF02
MAGIC = 0xFE
HEADER_LEN = 9
CMD_REQUEST = 0x10
CMD_NOTIFY = 0x11
NOTIFY_BATTERY = 0x01
CHARGE_BIT = 0x80


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=PAGE)) or any(
        _input_len(m) >= 32 for m in ctx.members)


def _input_len(member) -> int:
    from providers import hidreports
    try:
        inputs = hidreports.reports(member.get("path")).get("in", {})
    except Exception:
        return 0
    return max(inputs.values()) if inputs else 0


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_request(seq: int = 0) -> bytes:
    payload = bytes([0x09, 0x01, 0x00])
    frame = bytearray(HEADER_LEN + len(payload) + 2)
    frame[0] = MAGIC
    frame[1] = seq
    frame[2] = CMD_REQUEST
    frame[3] = 0x00
    frame[4] = 0x02
    frame[5] = 0x00
    frame[6] = 0x00
    frame[7] = len(payload)
    frame[8] = 0x00
    frame[9:9 + len(payload)] = payload
    crc = crc16(bytes(frame[:HEADER_LEN + len(payload)]))
    frame[-2] = crc >> 8
    frame[-1] = crc & 0xFF
    return bytes(frame)


def locate(raw: bytes):
    """返回 (cmd, 载荷) 或 None。"""
    for off in (0, 1):
        if len(raw) < off + HEADER_LEN + 2:
            continue
        if raw[off] != MAGIC:
            continue
        payload_len = raw[off + 7]
        end = off + HEADER_LEN + payload_len
        if end + 2 > len(raw):
            continue
        want = (raw[end] << 8) | raw[end + 1]
        if crc16(raw[off:end]) != want:
            continue
        return raw[off + 2], bytes(raw[off + HEADER_LEN:end])
    return None


def parse_battery(raw: bytes):
    hit = locate(raw)
    if hit is None:
        return None
    cmd, payload = hit
    if cmd == CMD_REQUEST:
        return None                        # 自己写出去的帧被回显，不是应答
    if cmd != CMD_NOTIFY or len(payload) < 2 or payload[0] != NOTIFY_BATTERY:
        return None

    data_len = min(payload[1], len(payload) - 2)
    if data_len <= 0:
        return None

    def value(byte: int):
        percent = byte & ~CHARGE_BIT & 0x7F
        return (percent if 1 <= percent <= 100 else None), bool(byte & CHARGE_BIT)

    if data_len == 1:
        percent, charging = value(payload[2])
        return (percent, charging) if percent is not None else None

    slots = [value(payload[2 + i])[0] if data_len > i else None for i in range(3)]
    charging = any(value(payload[2 + i])[1] for i in range(data_len))
    ears = [v for v in slots[:2] if v is not None]
    percent = min(ears) if ears else slots[2]
    if percent is None:
        return None
    return percent, charging


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE) or [m for m in ctx.members if _input_len(m) >= 32]
    if not targets:
        return None
    key = ("darkrim", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            out_len = max(_out_len(member), 16)
            rid = _output_id(member)
            frame = bytearray(out_len)
            frame[0] = rid
            request = build_request()
            frame[1:1 + len(request)] = request
            if not base.write(dev, bytes(frame)):
                continue
            hit = base.wait_for(dev, parse_battery, ms=2200, size=out_len)
            if hit is None:
                continue
            percent, charging = hit
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·寸渊影弑",
                           model="寸渊影弑 SHADOW", kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None


def _out_len(member) -> int:
    from providers import hidreports
    try:
        outs = hidreports.reports(member.get("path")).get("out", {})
    except Exception:
        return 0
    return max(outs.values()) if outs else 0


def _output_id(member) -> int:
    from providers import hidreports
    try:
        outs = hidreports.reports(member.get("path")).get("out", {})
    except Exception:
        return 0
    if len(outs) == 1:
        return next(iter(outs))
    return 0
