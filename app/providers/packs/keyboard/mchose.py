# -*- coding: utf-8 -*-
"""【键盘】迈从 MCHOSE V1 系列键盘、K7 V2 Ultra+、新代 QHW dongle

适配设备
    迈从 V1 系列键盘    3837:41E4 / 3837（20/20 字节接口）
                        G87 / G87 V2 / K99 / X75 / G98 / Z75 / GX87 …
                        型号码从会话 ACK 反查（见 MODEL_BY_PASSWORD）
    迈从 K7 V2 Ultra+   3837:1018，接口 0xFF01/0x0001，64/64
    迈从 新代 QHW dongle  3837:3033 等，描述符里有 report 0x4D
                        可能接键盘也可能接鼠标，型号交给产品名判定
    共用 3554:FA09 的键盘  迈从 G75 系列（与 AULA F99、凌豹 K98 同指纹）

怎么认
    V1：厂商页且输入输出都恰好 20 字节。
    K7：3837:1018 + 0xFF01/0x0001。
    QHW：输出 ≥10 且描述符里有 report 0x4D；没有 0x4D 时退化为
         "厂商接口输出 ≥10 字节"，具体是不是由 probe 里的握手写来确认
         （写失败立刻返回，不空等）。
    3554:FA09 上与 AULA F99、凌豹 K98 同指纹，靠会话 ACK 的 6 字节型号密码
    查表定归属；型号不在表里就让位，绝不拿别人的帧报电量。

怎么读
    V1 键盘：会话 `13 05 01`（校验 = 前 19 字节之和），等 0A 推送
            （type 0x05、电量 [6]、标志 [7]）或 4A 应答（[5] 电量、[6] 标志），
            标志 bit4 = 充电；会话期没读到再发 `13 4A 01`。
    K7：`4D 01 01 <len> <cmdLo> <cmdHi> 00 00 <payload…> <xor>`，
        xor 覆盖 [2 .. 7+len]，且只有 flags == 1 才算（官方 i1e 原样行为）。
        发 0x0900 读设备信息，应答 payload[10]=连接、[11]=充电、[12]=电量；
        "只回 1 字节 0xFF"也是应答（鼠标在睡），不当失败。
    QHW：官方握手 `4D AA 55 AA 55 AA 55 00…` → 等 1 秒自推
        `FA FB 07 <电量> <充电>` → 没等到就发 `4D 01 03 00 04 09 00 <seq> <xor>`。

注意
    迈从鼠标在 mouse/mchose.py，耳机在 headset/mchose.py。
    QHW dongle 的 kind 交给产品名判，不写死成键盘。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading
from providers.packs.keyboard import _compx

VID = 0x3837
VID_LEGACY = 0x41E4
A5_PID = 0x100C
K7_PID = 0x1018
GMOUSE_PID = 0x4245
X9_PID = 0x6045

# V1
V1_RID = 0x13
V1_SESSION = 0x05
V1_QUERY = 0x4A
V1_PUSH = 0x0A
V1_PUSH_BATTERY = 0x05
V1_LEN = 20

# K7
K7_RID = 0x4D

# 新代 dongle（QHW）
QHW_RID = 0x4D
QHW_CMD_BATTERY = 0x0904
QHW_HANDSHAKE = bytes([0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55])
QHW_PUSH = (0xFA, 0xFB, 0x07)
_qhw_seq = 0

MODEL_BY_PASSWORD = {
    "03000000021C": "G87",
    "030000000077": "K99",
    "0300000001DF": "K99 V2",
    "030000000132": "G98",
    "0300000000D6": "X75",
    "0A0000000003": "G98 Pro",
    "0300000001C6": "X75 V2",
    "030000000115": "G75 Pro",
    "0A0000000018": "G98 V2",
    "0A000000002B": "UT98",
    "0A0000000001": "Z75",
    "0A0000000009": "Z75S",
    "0300000001C7": "KX75",
    "030000000174": "GX87",
    "0300000001ED": "GX87 V2",
    "030000000135": "K87",
    "030000000335": "G75 V2",
    "0A0000000034": "G87 V2",
}


def _has_v1(ctx: Ctx) -> bool:
    return any(base.io_lengths(m) == (V1_LEN, V1_LEN) for m in ctx.members)


def kind_of(ctx: Ctx) -> str | None:
    """本目录负责的四条链路：'kb_shared' / 'k7' / 'kb' / 'qhw'。"""
    # 3554:FA09 与 AULA F99 Pro、凌豹 K98 共用指纹：只能靠会话 ACK 的型号密码定归属
    if ctx.vid == _compx.VID and ctx.pid == _compx.PID:
        return "kb_shared" if _has_v1(ctx) else None

    if ctx.vid not in (VID, VID_LEGACY):
        return None

    # 这几个号段属于鼠标与耳机，交由各自目录，避免抢应答帧
    if ctx.pid in (A5_PID, GMOUSE_PID, X9_PID):
        return None

    if ctx.pid == K7_PID and ctx.pick(page_=0xFF01, usage_=0x0001):
        return "k7"

    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        if base.io_lengths(member) == (V1_LEN, V1_LEN):
            return "kb"

    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        ins, outs = base.io_lengths(member)
        if outs >= 10 and QHW_RID in base.out_reports(member):
            return "qhw"
    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        if base.io_lengths(member)[1] >= 10:
            return "qhw"
    return None


def match(ctx: Ctx) -> bool:
    return kind_of(ctx) is not None


def _targets(ctx: Ctx, kind: str) -> list[dict]:
    if kind == "kb":
        return [m for m in ctx.members if base.io_lengths(m) == (V1_LEN, V1_LEN)]
    if kind == "kb_shared":
        return _compx.targets(ctx)
    if kind == "k7":
        return ctx.pick(page_=0xFF01, usage_=0x0001)
    with_rid = [m for m in ctx.members if QHW_RID in base.out_reports(m)]
    if with_rid:
        return with_rid
    vendors = [m for m in ctx.members
               if base.page(m) >= 0xFF00 or base.usage(m) >= 0xFF00]
    return sorted(vendors or ctx.members,
                  key=lambda m: base.io_lengths(m)[1], reverse=True)


# ---------------- V1 键盘 ----------------
def v1_frame(command: int, param: int) -> bytes:
    frame = bytearray(V1_LEN)
    frame[0] = V1_RID
    frame[1] = command
    frame[2] = param
    frame[-1] = sum(frame[:-1]) & 0xFF
    return bytes(frame)


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


def v1_model(raw: bytes) -> str | None:
    for off in (0, 1):
        if len(raw) < off + 12:
            continue
        if raw[off] != V1_RID or raw[off + 1] != V1_SESSION:
            continue
        for start in (off + 5, off + 6):
            key = bytes(raw[start:start + 6]).hex().upper()
            if key in MODEL_BY_PASSWORD:
                return MODEL_BY_PASSWORD[key]
    return None


def _kb_probe(dev, require_known: bool = False):
    base.drain(dev)
    base.write(dev, v1_frame(V1_SESSION, 0x01))
    session_read = None
    model_ok = False
    for _ in range(4):
        raw = base.read(dev, 300, V1_LEN)
        if raw is None:
            continue
        if v1_model(raw) is not None:
            model_ok = True
        hit = v1_read(raw)
        if hit is not None and session_read is None:
            session_read = hit
        if session_read is not None and (not require_known or model_ok):
            return session_read
    if require_known and not model_ok:
        return None                          # 型号不在迈从表里：让给 AULA / 凌豹
    if session_read is not None:
        return session_read
    for _ in range(2):
        if not base.write(dev, v1_frame(V1_QUERY, 0x01)):
            continue
        for _ in range(4):
            raw = base.read(dev, 300, V1_LEN)
            if raw is None:
                continue
            hit = v1_read(raw)
            if hit is not None:
                return hit
    return None


# ---------------- K7 ----------------
def k7_frame(command: int, payload: bytes = b"") -> bytes:
    frame = bytearray(64)
    frame[0] = 0x4D
    frame[1] = 0x01
    frame[2] = 0x01
    frame[3] = len(payload)
    frame[4] = command & 0xFF
    frame[5] = command >> 8
    frame[6] = 0
    frame[7] = 0
    frame[8:8 + len(payload)] = payload
    value = 0
    for byte in frame[2:8 + len(payload)]:
        value ^= byte
    frame[8 + len(payload)] = value
    return bytes(frame)


def k7_locate(raw: bytes, command: int | None = None):
    for off in (0, 1):
        if len(raw) < off + 8:
            continue
        if raw[off] != 0x4D or raw[off + 1] != 0x01:
            continue
        declared = raw[off + 3]
        if len(raw) < off + 8 + declared:
            continue
        if command is not None:
            got = raw[off + 4] | (raw[off + 5] << 8)
            if got != command:
                continue
        return off + 8, declared
    return None


def k7_parse(raw: bytes):
    hit = k7_locate(raw, 0x0900)
    if hit is None:
        return None
    start, length = hit
    if length < 14:
        return None
    percent = raw[start + 12]
    if percent < 1 or percent > 100:
        return None
    connect, charge = raw[start + 10], raw[start + 11]
    return percent, charge, connect


def _k7_probe(dev):
    query = k7_frame(0x0900)
    for _ in range(3):
        if not base.write(dev, query):
            return None
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            raw = base.read(dev, 250, 64)
            if raw is None:
                continue
            if bytes(raw) == query:
                continue                      # 自己的写被回显
            hit = k7_parse(raw)
            if hit is not None:
                percent, charge, _ = hit
                if charge == 2:
                    return percent, False     # 已充满
                if charge in (0, 1):
                    return percent, charge == 1
                return percent, None
        time.sleep(0.15)
    return None


# ---------------- 新代 dongle（QHW） ----------------
def qhw_handshake(out_len: int) -> bytes:
    """官方握手：`4D AA 55 AA 55 AA 55 00…`。

    非 QHW 通道的描述符里没有 report 0x4D，这条写必然失败 —— 这正是"不是这条
    通道"的判据，写失败就立刻放弃，不空等。
    """
    frame = bytearray(max(out_len, 8))
    frame[0] = QHW_RID
    frame[1:1 + len(QHW_HANDSHAKE)] = QHW_HANDSHAKE
    return bytes(frame)


def qhw_query(out_len: int) -> bytes:
    """`4D 01 03 00 04 09 00 <seq> <xor>`，xor 覆盖 [1..7]。"""
    global _qhw_seq
    frame = bytearray(max(out_len, 10))
    frame[0] = QHW_RID
    frame[1] = 0x01                      # version
    frame[2] = 0x03                      # flags
    frame[3] = 0x00                      # payload 长度
    frame[4] = QHW_CMD_BATTERY & 0xFF    # 0x04
    frame[5] = QHW_CMD_BATTERY >> 8      # 0x09
    frame[6] = 0x00
    frame[7] = _qhw_seq & 0xFF
    _qhw_seq = (_qhw_seq + 1) & 0xFF
    xor = 0
    for byte in frame[1:8]:
        xor ^= byte
    frame[8] = xor
    return bytes(frame)


def qhw_parse_push(raw: bytes):
    """CZ 自发电量推送：`FA FB 07 <电量> <充电>`（0 放电 / 1 充电 / 2 充满）。"""
    if raw is None:
        return None
    for off in (0, 1):
        if len(raw) < off + 5:
            continue
        if (raw[off], raw[off + 1], raw[off + 2]) != QHW_PUSH:
            continue
        percent, charge = raw[off + 3], raw[off + 4]
        if percent <= 1 or percent > 100 or charge > 2:
            return None
        return percent, charge != 0
    return None


def qhw_parse(raw: bytes):
    """电量应答：`4D 01 … 04 09 00 <seq> <充电> <电量>`。

    [8]=充电状态（0 放电 / 1 充电 / 2 充满）、[9]=电量。
    电量 ≤1 是休眠/关机时的占位帧，一律作废。
    """
    if raw is None:
        return None
    for off in (0, 1):
        if len(raw) < off + 10:
            continue
        if raw[off] != QHW_RID or raw[off + 1] != 0x01:
            continue
        if raw[off + 4] != (QHW_CMD_BATTERY & 0xFF) or raw[off + 5] != (QHW_CMD_BATTERY >> 8):
            continue
        charge, percent = raw[off + 8], raw[off + 9]
        if percent <= 1 or percent > 100 or charge > 2:
            return None
        return percent, charge != 0
    return None


def _qhw_probe(dev, out_len: int):
    base.drain(dev)
    if not base.write(dev, qhw_handshake(out_len)):
        return None                      # 写不进去 = 不是 QHW 通道
    # 握手后官方固件会主动推一次，先白听一会儿
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        raw = base.read(dev, 200, 64)
        hit = qhw_parse_push(raw) if raw is not None else None
        if hit is not None:
            return hit
    frame = qhw_query(out_len)
    for _ in range(2):
        if not base.write(dev, frame):
            return None
        end = time.monotonic() + 1.6
        while time.monotonic() < end:
            raw = base.read(dev, 250, 64)
            if raw is None:
                continue
            hit = qhw_parse_push(raw) or qhw_parse(raw)
            if hit is not None:
                return hit
    return None


# ---------------- 入口 ----------------
def _model(ctx: Ctx, kind: str) -> str:
    if kind == "k7":
        return "迈从 K7 V2 Ultra+"
    name = ctx.name or ""
    for word in ("MCHOSE", "2.4G", "Wireless", "Dongle", "Receiver"):
        name = name.replace(word, "")
    name = name.strip(" -_")
    return f"迈从 {name}".strip() if name else f"迈从 ({ctx.vid_pid})"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    kind = kind_of(ctx)
    if kind is None:
        return None
    targets = _targets(ctx, kind)
    if not targets:
        return None
    key = ("mchose-kb", kind, ctx.phys)
    if base.cooled(key, force):
        return None

    model = _model(ctx, kind)
    if kind == "k7":
        dev_kind = base.KEYBOARD
    elif kind == "qhw":
        # 新代 dongle 可能接键也可能接鼠，交给产品名去判，别写死
        dev_kind = base.UNKNOWN
    else:
        dev_kind = base.KEYBOARD

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            outs = base.io_lengths(member)[1]
            if kind == "kb":
                hit = _kb_probe(dev)
            elif kind == "kb_shared":
                hit = _kb_probe(dev, require_known=True)
            elif kind == "k7":
                hit = _k7_probe(dev)
            else:
                hit = _qhw_probe(dev, outs or 64)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·迈从",
                           model=model, kind=dev_kind)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
