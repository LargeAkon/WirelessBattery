# -*- coding: utf-8 -*-
"""雷蛇 RAZER：四条已验证过的链路，全部来自 OpenRazer / 官方 Synapse 逆向。

1) 经典 90 字节 feature（毒蝰 V4 Pro 00E6 与本体 00E5）
   report ID 0，缓冲 91 字节；请求 `00 <txn> 00 00 00 02 07 <cmd> … <xor> 00`，
   校验 = payload[2..87] **逐字节异或**（OpenRazer 里叫 crc，其实不是 CRC-8）。
   电量原始值在缓冲 [10]，按 0..255 线性映射；充电命令 0x84，1 = 充电中。
   91 字节本身就是判据：同一台设备另有 62 字节的 0xFF13 接口，靠长度分开。
   事务号先用 0x1F，没应答再试 0xFF（OpenRazer 对未知型号的默认值）。

2) 毒蝰 Viper V3 Pro SE（00DF）
   同 90 字节帧，但接口判据更严：usage 0x0001/0x0002、mi_00，且应答必须
   payload[88] 校验通过、payload[89] == 0。电量四舍五入 (raw×100+127)/255。

3) BlackShark V2 Pro 2023（0555）—— PA 远程模式
   64 字节帧、report ID 2；必须先发**两次** remote-mode-on（`… 0E … E1 01`）才能查询，
   拿到读数后**必须**发一次 remote-mode-off 归还会话，否则耳机停在远程模式。
   应答 `02 80 … 50 49 … <cmd> 01 01 <值>`，[15] 是电量或充电标志。

4) Kraken V4 接收器（056C）
   64 字节帧、report ID 2、usage 0xFF14/1；校验请求覆盖 [0..61]、应答覆盖 [1..61]，
   电量/充电值在 [13]。命令 0x21 电量、0x2A 充电。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x1532

# 经典 90 字节
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

# Viper SE
SE_PID = 0x00DF

# PA 耳机
HEADSET_PID = 0x0555
PA_LEN = 64
PA_RID = 2
PA_BATTERY = 0x21
PA_CHARGING = 0x2A

# Kraken V4
KRAKEN_PID = 0x056C
KRAKEN_PAGE = 0xFF14
KRAKEN_RID = 0x02
KRAKEN_LEN = 64
KRAKEN_TXN = 0x60
KRAKEN_BATTERY = 0x21
KRAKEN_CHARGING = 0x2A


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if ctx.pid in CLASSIC_PIDS or ctx.pid == SE_PID:
        return any(_feature_len(m) == CLASSIC_BUFFER for m in ctx.members)
    if ctx.pid == HEADSET_PID:
        return any(_page_usage(m) == (0xFF00, 0x0001)
                   and "&mi_03&col02#" in base.path_text(m).lower()
                   for m in ctx.members)
    if ctx.pid == KRAKEN_PID:
        return bool(ctx.pick(page_=KRAKEN_PAGE, usage_=0x0001))
    return False


def _feature_len(member) -> int:
    from providers import hidreports
    try:
        feats = hidreports.reports(member.get("path")).get("feat", {})
    except Exception:
        return 0
    return max(feats.values()) if feats else 0


def _page_usage(member) -> tuple[int, int]:
    return base.page(member), base.usage(member)


# ---------------- 经典 90 字节 ----------------
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


def _classic_probe(dev, pid: int):
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


# ---------------- Viper SE ----------------
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


# ---------------- PA 耳机 ----------------
def pa_envelope() -> bytearray:
    frame = bytearray(PA_LEN)
    frame[0] = PA_RID
    frame[1] = 0x80
    frame[5] = 0x50
    frame[6] = 0x41
    return frame


def pa_query(command: int) -> bytes:
    frame = pa_envelope()
    frame[2] = 8
    frame[7] = 8
    frame[9] = 3
    frame[10] = command
    return bytes(frame)


def pa_remote(enabled: bool) -> bytes:
    frame = pa_envelope()
    frame[2] = 7
    frame[7] = 0x0E
    frame[9] = 2
    frame[10] = 0xE1
    frame[11] = 1 if enabled else 0
    return bytes(frame)


def pa_parse(raw, command: int):
    if raw is None or len(raw) != PA_LEN:
        return None
    if raw[0] != PA_RID or raw[2] != 0x50 or raw[3] != 0x49:
        return None
    if raw[12] != command or raw[13] != 1 or raw[14] != 1:
        return None
    return raw[15]


def _pa_probe(dev):
    opened = False
    try:
        for _ in range(2):
            if not base.write(dev, pa_remote(True)):
                return None
            opened = True
            time.sleep(0.035)
        percent = None
        charging = None
        if base.write(dev, pa_query(PA_BATTERY)):
            deadline = time.monotonic() + 0.7
            while time.monotonic() < deadline:
                raw = base.read(dev, 100, PA_LEN)
                if raw is None:
                    continue
                value = pa_parse(raw, PA_BATTERY)
                if value is not None and value <= 100:
                    percent = value
                    break
        if percent is not None and base.write(dev, pa_query(PA_CHARGING)):
            deadline = time.monotonic() + 0.45
            while time.monotonic() < deadline:
                raw = base.read(dev, 100, PA_LEN)
                if raw is None:
                    continue
                value = pa_parse(raw, PA_CHARGING)
                if value is not None:
                    charging = value != 0
                    break
        if percent is None:
            return None
        return percent, charging
    finally:
        if opened:
            base.write(dev, pa_remote(False))      # 必须归还远程模式


# ---------------- Kraken V4 ----------------
def kraken_checksum(frame: bytes, start: int) -> int:
    value = 0
    for byte in frame[start:KRAKEN_LEN - 2]:
        value ^= byte
    return value


def kraken_query(command: int) -> bytes:
    frame = bytearray(KRAKEN_LEN)
    frame[0] = KRAKEN_RID
    frame[2] = KRAKEN_TXN
    frame[6] = 4
    frame[9] = 0x80
    frame[10] = command
    frame[11] = 0x00
    frame[12] = 0
    frame[KRAKEN_LEN - 2] = kraken_checksum(frame, 0)
    return bytes(frame)


def kraken_parse(raw, command: int):
    if raw is None or len(raw) != KRAKEN_LEN:
        return None
    if raw[0] != KRAKEN_RID or raw[1] != STATUS_OK or raw[2] != KRAKEN_TXN:
        return None
    if raw[10] != command or raw[11] != 0x01 or raw[12] != 1:
        return None
    if raw[KRAKEN_LEN - 2] != kraken_checksum(raw, 1):
        return None
    return raw[13]


def _kraken_probe(dev):
    base.drain(dev)
    if not base.write(dev, kraken_query(KRAKEN_BATTERY)):
        return None
    percent = None
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline and percent is None:
        raw = base.read(dev, 200, KRAKEN_LEN)
        if raw is None:
            continue
        value = kraken_parse(raw, KRAKEN_BATTERY)
        if value is not None and value <= 100:
            percent = value
    if percent is None:
        return None
    charging = None
    if base.write(dev, kraken_query(KRAKEN_CHARGING)):
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            raw = base.read(dev, 200, KRAKEN_LEN)
            if raw is None:
                continue
            value = kraken_parse(raw, KRAKEN_CHARGING)
            if value is not None and value <= 1:
                charging = value == 1
                break
    return percent, charging


# ---------------- 入口 ----------------
def _targets(ctx: Ctx):
    if ctx.pid in CLASSIC_PIDS or ctx.pid == SE_PID:
        return [m for m in ctx.members if _feature_len(m) == CLASSIC_BUFFER]
    if ctx.pid == HEADSET_PID:
        return [m for m in ctx.members
                if _page_usage(m) == (0xFF00, 0x0001)
                and "&mi_03&col02#" in base.path_text(m).lower()]
    if ctx.pid == KRAKEN_PID:
        return ctx.pick(page_=KRAKEN_PAGE, usage_=0x0001)
    return []


def _label(ctx: Ctx) -> tuple[str, str]:
    if ctx.pid in CLASSIC_PIDS:
        return "协议包·雷蛇", f"雷蛇 {CLASSIC_PIDS[ctx.pid]}"
    if ctx.pid == SE_PID:
        return "协议包·雷蛇", "雷蛇 Viper V3 Pro SE"
    if ctx.pid == HEADSET_PID:
        return "协议包·雷蛇", "雷蛇 BlackShark V2 Pro (2023)"
    return "协议包·雷蛇", "雷蛇 Kraken V4"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("razer", ctx.phys)
    if base.cooled(key, force):
        return None

    label, model = _label(ctx)
    kind = base.HEADSET if ctx.pid in (HEADSET_PID, KRAKEN_PID) else base.MOUSE

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            if ctx.pid in CLASSIC_PIDS:
                hit = _classic_probe(dev, ctx.pid)
            elif ctx.pid == SE_PID:
                hit = _se_probe(dev)
            elif ctx.pid == HEADSET_PID:
                hit = _pa_probe(dev)
            else:
                hit = _kraken_probe(dev)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label=label, model=model, kind=kind)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
