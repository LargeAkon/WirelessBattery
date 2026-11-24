# -*- coding: utf-8 -*-
"""AKG N9 Hybrid：0ECB:20D9 接收器，RACE 消息查询电量。

接口指纹（五条都对上才碰）：usage 0xFF13/1、62 字节双向、无 feature、输出 report 0x06、
路径含 &mi_03&col02#。

查询帧固定 10 字节 `06 07 80 05 5A 03 00 D6 0C 00`，应答是 62 字节报告：
    [0]=0x07  [1]=有效载荷长度  [2]=0x80  [3..] = RACE 消息流
RACE 消息可能被拆到多条报告里，按长度字段拼接；电量消息形如
    `05 5D 03 00 D6 0C 00 00 <电量>`（9 字节，[8] 是百分比）。

零长度之后的字节是设备旧缓存，哪怕看着像电量也必须忽略。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x0ECB
PID = 0x20D9
PAGE = 0xFF13
REPORT_LEN = 62
INPUT_ID = 0x07
OUTPUT_ID = 0x06
PAYLOAD_LIMIT = 59
MAX_MESSAGE = 1024

QUERY = bytes([0x06, 0x07, 0x80, 0x05, 0x5A, 0x03, 0x00, 0xD6, 0x0C, 0x00])


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    if not ctx.pick(page_=PAGE, usage_=0x0001):
        return False
    targets = [m for m in ctx.pick(page_=PAGE, usage_=0x0001)
               if "&mi_03&col02#" in base.path_text(m).lower()]
    return bool(targets)


def _targets(ctx: Ctx):
    return [m for m in ctx.pick(page_=PAGE, usage_=0x0001)
            if "&mi_03&col02#" in base.path_text(m).lower()]


def take_payload(raw: bytes):
    if len(raw) != REPORT_LEN or raw[0] != INPUT_ID or raw[2] != 0x80:
        return None
    length = raw[1]
    if length > PAYLOAD_LIMIT:
        return None
    return bytes(raw[3:3 + length])


def take_messages(pending: bytearray) -> list[bytes] | None:
    """从累积缓冲里切出完整 RACE 消息；结构异常返回 None。"""
    out = []
    while pending:
        if pending[0] != 5:
            return None
        if len(pending) < 4:
            break
        if pending[1] not in (0x5B, 0x5C, 0x5D):
            return None
        size = 4 + pending[2] + (pending[3] << 8)
        if size < 6 or size > MAX_MESSAGE:
            return None
        if len(pending) < size:
            break
        out.append(bytes(pending[:size]))
        del pending[:size]
    return out


def parse_battery(message: bytes):
    if message[0] != 5 or message[1] != 0x5D:
        return None
    if len(message) != 9 or message[4] != 0xD6 or message[5] != 0x0C:
        return None
    if message[6] != 0 or message[7] != 0:
        return None
    percent = message[8]
    return percent if percent <= 100 else None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("akg", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            frame = QUERY + bytes(REPORT_LEN - len(QUERY))
            if not base.write(dev, frame):
                continue

            pending = bytearray()
            percent = None
            deadline_tries = 12
            for _ in range(deadline_tries):
                raw = base.read(dev, 250, REPORT_LEN)
                if raw is None:
                    continue
                chunk = take_payload(raw)
                if chunk is None:
                    continue
                pending.extend(chunk)
                messages = take_messages(pending)
                if messages is None:
                    break                   # 流结构坏了，这一轮作废
                for message in messages:
                    value = parse_battery(message)
                    if value is not None:
                        percent = value
                        break
                if percent is not None:
                    break
            if percent is None:
                continue
            base.clear_fail(key)
            return Reading(percent, None, label="协议包·AKG",
                           model="AKG N9 Hybrid", kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
