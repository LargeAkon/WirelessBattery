# -*- coding: utf-8 -*-
"""【鼠标】凌豹 LINGBAO M5PRO Max

适配设备
    凌豹 M5PRO Max      3151:402D，接口 0xFFFF/0x0002，feature F7

怎么认
    VID:PID + 0xFFFF/0x0002 接口。注意凌豹的键盘 K98 走的是另一家芯片
    （3554:FA09），在 keyboard/lingbao.py，两条链路互不相干。

怎么读
    官方驱动同款 F7 状态查询（官方每 10 秒发一次，这里一次轮询发一条）：
        写 64 字节 payload（[0]=0xF7）→ 等 20ms → 读 65 字节 feature
    应答：`<ID 0> <ack 0/1> <返回码 0> <电量> <0x01> <充电位>`

注意
    ack 不是 0/1 或返回码非 0，说明这不是本命令的应答，一律丢弃。
    电量 ≤1 是休眠占位，判无效。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3151
PID = 0x402D
PAGE = 0xFFFF
USAGE = 0x0002
FEATURE_ID = 0x00
FEATURE_LEN = 65
CMD_STATUS = 0xF7
CHARGING_INDEX = 5


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=PAGE, usage_=USAGE))


def build_query() -> bytes:
    payload = bytearray(64)
    payload[0] = CMD_STATUS
    return bytes(payload)


def parse(raw: bytes):
    if len(raw) < CHARGING_INDEX + 1:
        return None
    if raw[0] != FEATURE_ID or raw[1] not in (0, 1) or raw[2] != 0:
        return None
    percent = raw[3]
    if percent <= 1 or percent > 100:      # 0/1 是休眠占位，不是真电量
        return None
    return percent, raw[CHARGING_INDEX] == 1


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("lingbao-ms", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            reply = base.feature_roundtrip(dev, FEATURE_ID, build_query(),
                                           FEATURE_LEN, wait_ms=20)
            hit = parse(reply) if reply else None
            if hit is None:
                continue
            base.clear_fail(key)
            percent, charging = hit
            return Reading(percent, charging, label="协议包·凌豹",
                           model="凌豹 M5PRO Max", kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
