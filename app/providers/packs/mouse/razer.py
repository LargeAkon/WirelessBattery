# -*- coding: utf-8 -*-
"""【鼠标】雷蛇 RAZER 毒蝰系列（经典 90 字节 feature 链路）

适配设备
    毒蝰 V4 Pro          1532:00E6 接收器 · 1532:00E5 有线本体
    毒蝰 Viper V3 Pro SE 1532:00DF 接收器
    同系列其他走 90 字节 feature 的型号，一般也能直接读。

怎么认
    report ID 0、缓冲 91 字节（90 字节 payload）。91 字节本身就是判据：
    同一台设备另有 62 字节的 0xFF13 接口，靠长度分开。
    Viper SE 的判据更严：接口必须是 usage 0x0001/0x0002、mi_00。

怎么读
    请求 `00 <txn> 00 00 00 02 07 <cmd> … <xor> 00`，
    校验 = payload[2..87] **逐字节异或**（OpenRazer 里叫 crc，其实不是 CRC-8）。
    电量原始值在缓冲 [10]，按 0..255 线性映射；充电命令 0x84，1 = 充电中。
    事务号先用 0x1F，没应答再试 0xFF（OpenRazer 对未知型号的默认值）。
    Viper SE 的应答额外要求 payload[88] 校验通过、payload[89] == 0，
    电量四舍五入 (raw×100+127)/255。

注意
    雷蛇的耳机（BlackShark V2 Pro 2023、Kraken V4）在 headset/razer.py。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x1532

CLASSIC_PIDS = {0x00E6: "毒蝰 V4 Pro", 0x00E5: "毒蝰 V4 Pro（有线）"}
CLASSIC_PAYLOAD = 90
CLASSIC_BUFFER = 91
CLASSIC_TXN = 0x1F
CLASS_BATTERY = 0x07
CMD_BATTERY = 0x80
CMD_CHARGING = 0x84
STATUS_OK = 0x02
STATUS_BUSY = 0x01
STATUS_NONE = 0x04

SE_PID = 0x00DF


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if ctx.pid in CLASSIC_PIDS or ctx.pid == SE_PID:
        return any(base.feature_length(m) == CLASSIC_BUFFER for m in ctx.members)
    return False


def classic_checksum(payload: bytes) -> int:
    value = 0
    for byte in payload[2:88]:
        value ^= byte
    return value


def classic_request(command: int, txn: int) -> bytes:
    payload = bytearray(CLASSIC_PAYLOAD)
    payload[1] = txn
    payload[5] = 0x02
    payload[6] = CLASS_BATTERY
    payload[7] = command
    payload[88] = classic_checksum(payload)
    return bytes(payload)


def classic_echo(raw, command: int) -> bool:
    if raw is None or len(raw) < CLASSIC_BUFFER:
        return False
    if raw[1] in (STATUS_BUSY, STATUS_NONE) or raw[1] != STATUS_OK:
        return False
    return raw[7] == CLASS_BATTERY and raw[8] == command


def classic_percent(raw) -> int:
    value = raw[10]
    return min(max(value * 100 // 255, 0), 100)


def _classic_probe(dev):
    for txn in (CLASSIC_TXN, 0xFF):
        reply = base.feature_roundtrip(dev, 0, classic_request(CMD_BATTERY, txn),
                                       CLASSIC_BUFFER, wait_ms=60)
        if not classic_echo(reply, CMD_BATTERY):
            continue
        percent = classic_percent(reply)
        charging = None
        charge = base.feature_roundtrip(dev, 0, classic_request(CMD_CHARGING, txn),
                                        CLASSIC_BUFFER, wait_ms=40)
        if classic_echo(charge, CMD_CHARGING):
            flag = charge[10]
            if flag == 0x01:
                charging = True
            elif flag == 0x00:
                charging = False
        return percent, charging
    return None


def se_parse(raw):
    if raw is None or len(raw) != CLASSIC_BUFFER or raw[0] != 0:
        return None
    payload = raw[1:]
    if payload[0] != STATUS_OK or payload[1] != CLASSIC_TXN:
        return None
    if payload[2] != 0 or payload[3] != 0 or payload[4] != 0:
        return None
    if payload[5] != 2 or payload[6] != CLASS_BATTERY or payload[7] != CMD_BATTERY:
        return None
    if payload[88] != classic_checksum(payload) or payload[89] != 0:
        return None
    return (payload[9] * 100 + 127) // 255


def _se_probe(dev):
    reply = base.feature_roundtrip(dev, 0, classic_request(CMD_BATTERY, CLASSIC_TXN),
                                   CLASSIC_BUFFER, wait_ms=60)
    percent = se_parse(reply)
    if percent is None:
        return None
    charging = None
    charge = base.feature_roundtrip(dev, 0, classic_request(CMD_CHARGING, CLASSIC_TXN),
                                    CLASSIC_BUFFER, wait_ms=40)
    if charge is not None and len(charge) > 10:
        payload = charge[1:]
        if payload[7] == CMD_CHARGING and payload[88] == classic_checksum(payload):
            flag = payload[9]
            if flag <= 1:
                charging = flag == 1
    return percent, charging


def _targets(ctx: Ctx) -> list[dict]:
    return [m for m in ctx.members
            if base.feature_length(m) == CLASSIC_BUFFER]


def _label(ctx: Ctx) -> str:
    if ctx.pid in CLASSIC_PIDS:
        return f"雷蛇 {CLASSIC_PIDS[ctx.pid]}"
    return "雷蛇 Viper V3 Pro SE"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("razer-mouse", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = _se_probe(dev) if ctx.pid == SE_PID else _classic_probe(dev)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·雷蛇",
                           model=_label(ctx), kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
