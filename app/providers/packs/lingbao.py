# -*- coding: utf-8 -*-
"""凌豹 LINGBAO：M5PRO Max（feature F7）与 K98 键盘（0x13 会话）。

M5PRO Max（3151:402D）：官方驱动同款 F7 状态查询。
    官方驱动每 10 秒发一次 `00 F7 00…`（无校验和），这里一次轮询发一条：
        写 64 字节 payload（[0]=0xF7）→ 等 20ms → 读 65 字节 feature
    应答：`<ID 0> <ack 0/1> <返回码 0> <电量> <0x01> <充电位>`
    ack 不是 0/1 或返回码非 0 说明这不是本命令的应答，一律丢弃。

K98（3554:FA09，0xFF02/2，20/20）：与 AULA F99 Pro、迈从 G75 共用 VID:PID，
    只能靠会话 ACK 的型号码分流（K98 = 0x0212）。
    会话帧 `13 05 01`，之后解析 0A 电量推送（type 0x05）或 4A 查询应答；
    型号不是 0x0212 就立刻让位，绝不拿别人的帧报电量。
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

COMPX_VID = 0x3554
COMPX_PID = 0xFA09
K98_MODEL = 0x0212
V1_RID = 0x13
V1_SESSION = 0x05
V1_QUERY = 0x4A
V1_PUSH = 0x0A
V1_PUSH_BATTERY = 0x05
V1_LEN = 20


def _v1_targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.pick(page_=0xFF02, usage_=0x0002) if _io(m) == (V1_LEN, V1_LEN)]


def _io(member) -> tuple[int, int]:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return 0, 0
    ins = reports.get("in", {}).values()
    outs = reports.get("out", {}).values()
    return max(ins, default=0), max(outs, default=0)


def match(ctx: Ctx) -> bool:
    if ctx.vid == VID and ctx.pid == PID:
        return bool(ctx.pick(page_=PAGE, usage_=USAGE))
    if ctx.vid == COMPX_VID and ctx.pid == COMPX_PID:
        return bool(_v1_targets(ctx))
    return False


def query_frame() -> bytes:
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
    if ctx.vid == COMPX_VID:
        return _probe_k98(ctx, force)
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("lingbao", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            reply = base.feature_roundtrip(dev, FEATURE_ID, query_frame(),
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


# ---------------- K98 ----------------
def v1_frame(command: int, param: int) -> bytes:
    frame = bytearray(V1_LEN)
    frame[0] = V1_RID
    frame[1] = command
    frame[2] = param
    frame[-1] = sum(frame[:-1]) & 0xFF
    return bytes(frame)


def v1_model_code(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 12:
            continue
        if raw[off] != V1_RID or raw[off + 1] != V1_SESSION or raw[off + 2] != 0x01:
            continue
        return (raw[off + 9] << 8) | raw[off + 10]
    return None


def v1_read(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 8:
            continue
        if raw[off] != V1_RID:
            continue
        if raw[off + 1] == V1_PUSH:
            if raw[off + 5] != V1_PUSH_BATTERY:
                return None
            percent, flag = raw[off + 6], raw[off + 7]
        elif raw[off + 1] == V1_QUERY:
            if len(raw) < V1_LEN:
                return None
            percent, flag = raw[off + 5], raw[off + 6]
        else:
            return None
        if percent <= 1 or percent > 100:
            return None
        return percent, bool(flag & 0x10)
    return None


def _probe_k98(ctx: Ctx, force: bool) -> Reading | None:
    targets = _v1_targets(ctx)
    if not targets:
        return None
    key = ("lingbao-k98", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, v1_frame(V1_SESSION, 0x01)):
                continue
            session_read = None
            model = None
            for _ in range(4):
                raw = base.read(dev, 300, V1_LEN)
                if raw is None:
                    continue
                code = v1_model_code(raw)
                if code is not None:
                    if code != K98_MODEL:
                        break                # 是 F99 Pro / G75：让位
                    model = code
                    continue
                hit = v1_read(raw)
                if hit is not None and session_read is None:
                    session_read = hit
            if model is None:
                continue
            if session_read is not None:
                base.clear_fail(key)
                return Reading(session_read[0], session_read[1],
                               label="协议包·凌豹", model="凌豹 K98",
                               kind=base.KEYBOARD)
            for _ in range(2):
                if not base.write(dev, v1_frame(V1_QUERY, 0x01)):
                    continue
                for _ in range(4):
                    raw = base.read(dev, 300, V1_LEN)
                    if raw is None:
                        continue
                    hit = v1_read(raw)
                    if hit is not None:
                        base.clear_fail(key)
                        return Reading(hit[0], hit[1], label="协议包·凌豹",
                                       model="凌豹 K98", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
