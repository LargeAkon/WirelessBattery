# -*- coding: utf-8 -*-
"""【耳机】雷蛇 RAZER BlackShark V2 Pro 2023、Kraken V4

适配设备
    BlackShark V2 Pro (2023)    1532:0555，PA 远程模式（report 2，64 字节）
    Kraken V4 接收器            1532:056C，接口 0xFF14/0x0001（report 2，64 字节）

怎么认
    BlackShark：接口 0xFF00/0x0001 且路径含 &mi_03&col02#。
    Kraken V4：接口 0xFF14/0x0001。

怎么读
    BlackShark（PA 远程模式）：
        必须先发**两次** remote-mode-on（`… 0E … E1 01`）才能查询；
        应答 `02 80 … 50 49 … <cmd> 01 01 <值>`，[15] 是电量或充电标志；
        拿到读数后**必须**发一次 remote-mode-off 归还会话，否则耳机停在远程模式
        —— 这一步写在 finally 里，读失败也会执行。
    Kraken V4：
        校验请求覆盖 [0..61]、应答覆盖 [1..61]，电量/充电值在 [13]。
        命令 0x21 电量、0x2A 充电。

注意
    雷蛇的鼠标（毒蝰系列，90 字节 feature）在 mouse/razer.py。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x1532

HEADSET_PID = 0x0555
PA_LEN = 64
PA_RID = 2
PA_BATTERY = 0x21
PA_CHARGING = 0x2A

KRAKEN_PID = 0x056C
KRAKEN_PAGE = 0xFF14
KRAKEN_RID = 0x02
KRAKEN_LEN = 64
KRAKEN_TXN = 0x60
KRAKEN_BATTERY = 0x21
KRAKEN_CHARGING = 0x2A

STATUS_OK = 0x02


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if ctx.pid == HEADSET_PID:
        return any(base.page(m) == 0xFF00 and base.usage(m) == 0x0001
                   and "&mi_03&col02#" in base.path_text(m).lower()
                   for m in ctx.members)
    if ctx.pid == KRAKEN_PID:
        return bool(ctx.pick(page_=KRAKEN_PAGE, usage_=0x0001))
    return False


# ---------------- PA 耳机（BlackShark V2 Pro 2023） ----------------
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
def _targets(ctx: Ctx) -> list[dict]:
    if ctx.pid == HEADSET_PID:
        return [m for m in ctx.members
                if base.page(m) == 0xFF00 and base.usage(m) == 0x0001
                and "&mi_03&col02#" in base.path_text(m).lower()]
    if ctx.pid == KRAKEN_PID:
        return ctx.pick(page_=KRAKEN_PAGE, usage_=0x0001)
    return []


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("razer-headset", ctx.phys)
    if base.cooled(key, force):
        return None

    if ctx.pid == HEADSET_PID:
        model = "雷蛇 BlackShark V2 Pro (2023)"
    else:
        model = "雷蛇 Kraken V4"

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            if ctx.pid == HEADSET_PID:
                hit = _pa_probe(dev)
            else:
                hit = _kraken_probe(dev)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·雷蛇",
                           model=model, kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
