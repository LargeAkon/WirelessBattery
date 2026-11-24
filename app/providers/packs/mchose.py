# -*- coding: utf-8 -*-
"""迈从 MCHOSE：七条链路，判据全部是完整接口指纹，不做"同 VID 就试试"。

1) 键盘 V1（3837 / 41E4，20/20 字节）—— G87 / G87 V2 / K99 / X75 …
   会话 `13 05 01`（校验 = 前 19 字节之和），等 0A 推送（type 0x05、电量 [6]、标志 [7]）
   或 4A 应答（[5] 电量、[6] 标志），标志 bit4 = 充电；会话期没读到再发 `13 4A 01`。
   会话 ACK 的 [5..10] 是型号密码，可反查型号名。

2) 鼠标 V2（3837 / 41E4，≥60 字节）—— G87 V2 / A7 V2 Pro 等
   接收器自发 E2 状态帧（整帧逐字节取反：[0]=0xE2、[3]=充电、[4]=电量）。
   先纯被动等 3 秒；等不到才发一次触发帧 `11 F9 FF…`（官方 MOUSE_LEGACY 同款），
   再等 3 秒。E2 帧是接收器自发流，主动查询只会干扰鼠标。

3) K7 V2 Ultra+（3837:1018，0xFF01/1，64/64）
   0x4D 帧：`4D 01 01 <len> <cmdLo> <cmdHi> 00 00 <payload…> <xor>`，
   **xor 覆盖 [2 .. 7+len]，且只有 flags == 1 才算**（官方 i1e 原样行为）。
   发 0x0900 读设备信息，应答 payload[10]=连接、[11]=充电、[12]=电量；
   "只回 1 字节 0xFF"也是应答（鼠标在睡），不当失败。

4) Gmouse（3837:4245，0xFF01/0x10，65/65）—— G3 V2
   查询 `00 55 30 A5 0B 2E 01 01 01`；应答 AA 30 前缀，[off+8] 电量、[off+9] 充电。

5) A5 V2 Ultra（3837:100C，0xFF01/1，feature ≥21）—— 反码 Feature 0x11
   SetFeature(0x11, `F9` + 19 个 0xFF) → 等输入通知（`13 xx F9`）→ GetFeature(0x11)。
   应答 [2..3]/[4..5] 是鼠标本体 VID/PID（取反），[11] 电量、[12] 充电（取反）。

6) V9 Pro 耳机（291D:385D，0xFF90/1，64/64，mi_00 第 5 个 collection）
7) X9 耳机（3837:6045，同结构，VID 与键鼠同号段，必须排在鼠标分支前）
   查询 `55 65 01`，应答 [1]=0x65、[2]=电量；X9 的 [3] 是充电状态
   （2 放电 / 3 充电 / 4 充满 / 0x1A 休眠）。有的接收器会把查询回显成 1% 应答，
   整帧等于查询帧时必须丢弃。
"""
from __future__ import annotations

import time

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x3837
VID_LEGACY = 0x41E4
V9_VID = 0x291D
V9_PID = 0x385D
X9_PID = 0x6045
A5_PID = 0x100C
K7_PID = 0x1018
GMOUSE_PID = 0x4245
COMPX_VID = 0x3554
COMPX_PID = 0xFA09

# V1
V1_RID = 0x13
V1_SESSION = 0x05
V1_QUERY = 0x4A
V1_PUSH = 0x0A
V1_PUSH_BATTERY = 0x05
V1_LEN = 20

# 鼠标 V2
V2_STATUS = 0xE2
V2_POKE_RID = 0x11
V2_POKE_CMD = 0x06

# 耳机
HS_RID = 0x55
HS_ECHO = 0x65
HS_LEN = 64

# 新代 dongle（QHW，如 3837:3033）
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


def _io(member) -> tuple[int, int]:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return 0, 0
    ins = reports.get("in", {}).values()
    outs = reports.get("out", {}).values()
    return max(ins, default=0), max(outs, default=0)


def _report_ids(member) -> dict:
    """该接口输出端点的 report ID → 总长度（QHW 靠 0x4D 这个 ID 认）。"""
    from providers import hidreports
    try:
        return hidreports.reports(member.get("path")).get("out", {})
    except Exception:
        return {}


def _feature(member) -> int:
    from providers import hidreports
    try:
        feats = hidreports.reports(member.get("path")).get("feat", {})
    except Exception:
        return 0
    return max(feats.values()) if feats else 0


def _is_headset_path(member) -> bool:
    return "&mi_00&col05#" in base.path_text(member).lower()


def _has_v1(ctx: Ctx) -> bool:
    return any(_io(m) == (V1_LEN, V1_LEN) for m in ctx.members)


def kind_of(ctx: Ctx) -> str | None:
    """返回 'kb' / 'kb_shared' / 'mouse' / 'k7' / 'gmouse' / 'a5' / 'v9' / 'x9' / None。"""
    if ctx.vid == V9_VID and ctx.pid == V9_PID:
        return "v9" if any(_is_headset_path(m) for m in ctx.members) else None
    # 3554:FA09 与 AULA F99 Pro、凌豹 K98 共用指纹：只能靠会话 ACK 的型号密码定归属
    if ctx.vid == COMPX_VID and ctx.pid == COMPX_PID:
        return "kb_shared" if _has_v1(ctx) else None
    if ctx.vid not in (VID, VID_LEGACY):
        return None
    if ctx.pid == X9_PID:
        return "x9" if any(_is_headset_path(m) for m in ctx.members) else None
    if ctx.pid == A5_PID and ctx.pick(page_=0xFF01, usage_=0x0001):
        return "a5" if any(_feature(m) >= 21 for m in ctx.members) else None
    if ctx.pid == K7_PID and ctx.pick(page_=0xFF01, usage_=0x0001):
        return "k7"
    if ctx.pid == GMOUSE_PID and ctx.pick(page_=0xFF01, usage_=0x0010):
        return "gmouse"
    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        ins, outs = _io(member)
        if ins == V1_LEN and outs == V1_LEN:
            return "kb"
    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        ins, outs = _io(member)
        if ins >= 60 and outs >= 60:
            return "mouse"
    # 新代 dongle（QHW）：描述符里有 report 0x4D，或厂商接口够长、别的指纹都没命中。
    # 具体是不是 QHW 由 probe 里的握手写来确认（写失败立刻返回，不会拖时间）。
    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        ins, outs = _io(member)
        if outs >= 10 and QHW_RID in _report_ids(member):
            return "qhw"
    for member in ctx.members:
        if base.page(member) < 0xFF00 and base.usage(member) < 0xFF00:
            continue
        if _io(member)[1] >= 10:
            return "qhw"
    return None


def match(ctx: Ctx) -> bool:
    return kind_of(ctx) is not None


def _targets(ctx: Ctx, kind: str):
    if kind == "v9":
        return [m for m in ctx.members if _is_headset_path(m)]
    if kind == "x9":
        return [m for m in ctx.members if _is_headset_path(m)]
    if kind == "a5":
        return ctx.pick(page_=0xFF01, usage_=0x0001)
    if kind == "k7":
        return ctx.pick(page_=0xFF01, usage_=0x0001)
    if kind == "gmouse":
        return ctx.pick(page_=0xFF01, usage_=0x0010)
    if kind == "kb":
        return [m for m in ctx.members if _io(m) == (V1_LEN, V1_LEN)]
    if kind == "kb_shared":
        return [m for m in ctx.members if _io(m) == (V1_LEN, V1_LEN)]
    if kind == "qhw":
        with_rid = [m for m in ctx.members if QHW_RID in _report_ids(m)]
        if with_rid:
            return with_rid
        vendors = [m for m in ctx.members
                   if base.page(m) >= 0xFF00 or base.usage(m) >= 0xFF00]
        return sorted(vendors or ctx.members, key=lambda m: _io(m)[1], reverse=True)
    return [m for m in ctx.members if _io(m)[0] >= 60 and _io(m)[1] >= 60]


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


# ---------------- 鼠标 V2 ----------------
def v2_parse(raw: bytes):
    for off in (1, 0):
        if len(raw) < off + 5:
            continue
        lo = bytes(byte ^ 0xFF for byte in raw[off:])
        if lo[0] != V2_STATUS:
            continue
        percent = lo[4]
        if percent == 0 or percent > 100:
            return None
        return percent, lo[3] == 1
    return None


def v2_poke(length: int) -> bytes:
    frame = bytearray(max(length, 2))
    frame[0] = V2_POKE_RID
    frame[1] = V2_POKE_CMD ^ 0xFF
    for i in range(2, len(frame)):
        frame[i] = 0xFF
    return bytes(frame)


def _mouse_probe(dev, length: int):
    hit = base.wait_for(dev, v2_parse, ms=1200)
    if hit is not None:
        return hit
    if not base.write(dev, v2_poke(length)):
        return None
    return base.wait_for(dev, v2_parse, ms=1400)


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


# ---------------- Gmouse ----------------
def gmouse_query() -> bytes:
    frame = bytearray(65)
    frame[1:9] = bytes([0x55, 0x30, 0xA5, 0x0B, 0x2E, 0x01, 0x01, 0x01])
    return bytes(frame)


def gmouse_parse(raw: bytes):
    for off in (0, 1):
        if len(raw) < off + 10:
            continue
        if raw[off] != 0xAA or raw[off + 1] != 0x30:
            continue
        percent = raw[off + 8]
        if percent < 1 or percent > 100:
            return None
        return percent, raw[off + 9] != 0
    return None


# ---------------- A5 V2 Ultra ----------------
def a5_payload() -> bytes:
    return bytes([0xF9]) + bytes([0xFF] * 19)


def a5_notification(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0] == 0x13 and raw[2] == 0xF9


def a5_parse(raw):
    if raw is None or len(raw) < 21 or raw[0] != 0x11 or raw[1] != 0xF9:
        return None
    vid = (raw[2] ^ 0xFF) | ((raw[3] ^ 0xFF) << 8)
    pid = (raw[4] ^ 0xFF) | ((raw[5] ^ 0xFF) << 8)
    if vid != 0x41E4 or pid not in (0x1101, 0x1102):
        return None
    level = raw[11] ^ 0xFF
    charge = raw[12] ^ 0xFF
    if level > 100 or charge > 2:
        return None
    return level, (None if charge == 2 else charge == 1)


def _a5_probe(dev):
    try:
        dev.send_feature_report(bytes([0x11]) + a5_payload())
    except Exception:
        return None
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        raw = base.read(dev, 100, 21)
        if raw is None or not a5_notification(raw):
            continue
        reply = base.feature_get(dev, 0x11, 21)
        return a5_parse(reply)
    return None


# ---------------- 耳机 V9 / X9 ----------------
def hs_query() -> bytes:
    frame = bytearray(HS_LEN)
    frame[0] = HS_RID
    frame[1] = HS_ECHO
    frame[2] = 0x01
    return bytes(frame)


def hs_parse(raw: bytes, with_status: bool):
    if raw is None or len(raw) != HS_LEN:
        return None
    if raw[0] != HS_RID or raw[1] != HS_ECHO:
        return None
    percent = raw[2]
    if percent == 0 or percent > 100:
        return None
    if bytes(raw) == hs_query():
        return None                          # 主机写入被回显
    if not with_status:
        return percent, None
    status = raw[3]
    if status == 0x02 or status == 0x1A:
        return percent, False
    if status == 0x03:
        return percent, True
    if status == 0x04:
        return percent, False
    return percent, None


def _hs_probe(dev, with_status: bool):
    base.drain(dev)
    if not base.write(dev, hs_query()):
        return None
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        raw = base.read(dev, 200, HS_LEN)
        if raw is None:
            continue
        hit = hs_parse(raw, with_status)
        if hit is not None:
            return hit
    return None


# ---------------- 入口 ----------------
# ---------------- 新代 dongle（QHW）----------------
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


def _model(ctx: Ctx, kind: str) -> str:
    if kind == "v9":
        return "迈从 V9 Pro"
    if kind == "x9":
        return "迈从 X9"
    if kind == "a5":
        return "迈从 A5 V2 Ultra"
    if kind == "k7":
        return "迈从 K7 V2 Ultra+"
    if kind == "gmouse":
        return "迈从 G3 V2"
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
    key = ("mchose", kind, ctx.phys)
    if base.cooled(key, force):
        return None

    model = _model(ctx, kind)
    if kind in ("v9", "x9"):
        dev_kind = base.HEADSET
    elif kind == "kb":
        dev_kind = base.KEYBOARD
    elif kind == "qhw":
        # 新代 dongle 可能接键也可能接鼠，交给产品名去判，别写死
        dev_kind = base.UNKNOWN
    else:
        dev_kind = base.MOUSE

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            ins, outs = _io(member)
            if kind == "kb":
                hit = _kb_probe(dev)
            elif kind == "kb_shared":
                hit = _kb_probe(dev, require_known=True)
            elif kind == "mouse":
                hit = _mouse_probe(dev, max(outs, 64))
            elif kind == "k7":
                hit = _k7_probe(dev)
            elif kind == "gmouse":
                base.drain(dev)
                hit = None
                if base.write(dev, gmouse_query()):
                    hit = base.wait_for(dev, gmouse_parse, ms=1100, size=65)
            elif kind == "a5":
                hit = _a5_probe(dev)
            elif kind == "x9":
                hit = _hs_probe(dev, with_status=True)
            elif kind == "qhw":
                hit = _qhw_probe(dev, outs or 64)
            else:
                hit = _hs_probe(dev, with_status=False)
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
