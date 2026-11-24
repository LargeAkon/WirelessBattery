# -*- coding: utf-8 -*-
"""狼蛛 AULA / 前行者：一个模块管四条链路。

1) F99 Pro（3554:FA09，0xFF02/2，20/20）—— 会话协议
   发 `13 05 01` 开会话，等 ACK（`13 05 01 …`，型号码在 [9..10]，F99 Pro = 0x0158）
   或 0A 电量推送（type [5]=0x05、电量 [6]、标志 [7]，标志 bit4 = 充电）；
   会话期没读到就再发 `13 4A 01` 查询，应答 [1]=0x4A、[5]=电量、[6]=标志。
   **3554:FA09 上还叠着迈从 G75 与凌豹 K98**，型号不是 0x0158 就必须让位，
   否则会拿别人的帧报自己的电量。

2) G9 耳机（38A6:0030，0xFFAB，输入 ≥9）—— 纯被动，零写入
   每秒一条 `AB 47 4D 86 …`：[6] = 电量、[7] = 充电（0x02 充电中）。
   旧固件（V0.0.4）电量与标志都恒 0，那是"没在报数"，不是真空电。

3) L9 Ultra 鼠标（38A6:28FD，0xFFA8）—— 发一条 `0B 81` 查询
   回包 `0A 81 …`：[18] = 电量、[17] = 充电（非 0 充电中）。

4) HERO 68 Air（372E:106C，0xFF60/0x61，20/20，report 0x09）—— Bytech 8K 分片
   先 `82 01` 查 UUID，应答里 6 字节必须是 `12 00 00 00 00 0A` 才认；
   再 `87 00` 查电量，应答 [6] = 电量、[7] 高 4 位 = 充电、低 4 位 = 已充满。
   响应被拆成 20 字节分片时要逐片回 ACK，否则设备不发下一片。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

# F99 Pro
F99_VID = 0x3554
F99_PID = 0xFA09
F99_PAGE = 0xFF02
F99_MODEL = 0x0158
V1_RID = 0x13
V1_SESSION = 0x05
V1_QUERY = 0x4A
V1_PUSH = 0x0A
V1_PUSH_BATTERY = 0x05
V1_FRAME = 20

# G9
G9_VID = 0x38A6
G9_PID = 0x0030
G9_PAGE = 0xFFAB
G9_RID = 0xAB
G9_LEVEL = 6
G9_CHARGE = 7

# L9
L9_VID = 0x38A6
L9_PID = 0x28FD
L9_PAGE = 0xFFA8
L9_OUT_ID = 0x0B
L9_IN_ID = 0x0A
L9_CMD = 0x81
L9_CHARGE_INDEX = 17
L9_LEVEL_INDEX = 18

# HERO 68 Air
HERO_VID = 0x372E
HERO_PID = 0x106C
HERO_PAGE = 0xFF60
HERO_USAGE = 0x0061
HERO_RID = 0x09
HERO_REPORT = 20
HERO_PACKET = 63
HERO_FRAG_PAYLOAD = 14


def match(ctx: Ctx) -> bool:
    if not (ctx.pid in (F99_PID, G9_PID, L9_PID, HERO_PID)):
        return False
    if ctx.vid not in (F99_VID, G9_VID, HERO_VID):
        return False
    return bool(_targets(ctx))


def _targets(ctx: Ctx) -> list[dict]:
    if ctx.vid == F99_VID and ctx.pid == F99_PID:
        return [m for m in ctx.pick(page_=F99_PAGE, usage_=0x0002)
                if _io(m) and min(_io(m)) >= V1_FRAME]
    if ctx.vid == G9_VID and ctx.pid == G9_PID:
        return [m for m in ctx.pick(page_=G9_PAGE) if _io(m)[0] >= 9]
    if ctx.vid == G9_VID and ctx.pid == L9_PID:
        return [m for m in ctx.pick(page_=L9_PAGE)
                if _io(m)[1] >= 3 and _io(m)[0] >= 11]
    if ctx.vid == HERO_VID and ctx.pid == HERO_PID:
        from providers import hidreports
        out = []
        for member in ctx.pick(page_=HERO_PAGE, usage_=HERO_USAGE):
            try:
                reports = hidreports.reports(member.get("path"))
            except Exception:
                continue
            if HERO_REPORT in reports.get("in", {}).values() and \
                    HERO_REPORT in reports.get("out", {}).values():
                out.append(member)
        return out
    return []


def _io(member) -> tuple[int, int]:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return 0, 0
    ins = reports.get("in", {}).values()
    outs = reports.get("out", {}).values()
    return max(ins, default=0), max(outs, default=0)


# ---------------- 通用 V1 帧（F99 Pro） ----------------
def v1_frame(command: int, param: int) -> bytes:
    frame = bytearray(V1_FRAME)
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
    """0A 推送 / 4A 响应 → (电量, 是否充电) 或 None。"""
    for off in (0, 1):
        if len(raw) < off + 8:
            continue
        if raw[off] != V1_RID:
            continue
        if raw[off + 1] == V1_PUSH:
            if raw[off + 5] != V1_PUSH_BATTERY:
                return None
            percent = raw[off + 6]
            flag = raw[off + 7]
        elif raw[off + 1] == V1_QUERY:
            if len(raw) < V1_FRAME:
                return None
            percent = raw[off + 5]
            flag = raw[off + 6]
        else:
            return None
        if percent <= 1 or percent > 100:
            return None
        return percent, bool(flag & 0x10)
    return None


# ---------------- G9 ----------------
def g9_parse(raw: bytes):
    if len(raw) <= G9_CHARGE:
        return None
    if raw[0] != G9_RID or raw[1] != 0x47 or raw[2] != 0x4D or raw[3] != 0x86:
        return None
    level = raw[G9_LEVEL]
    if level > 100:
        return None
    flag = raw[G9_CHARGE]
    if level == 0 and flag == 0:
        return None                          # 旧固件不报数
    return level, flag == 0x02


# ---------------- L9 ----------------
def l9_query(length: int) -> bytes:
    frame = bytearray(max(length, 3))
    frame[0] = L9_OUT_ID
    frame[1] = L9_CMD
    return bytes(frame)


def l9_parse(raw: bytes):
    if len(raw) <= L9_LEVEL_INDEX:
        return None
    if raw[0] != L9_IN_ID or raw[1] != L9_CMD:
        return None
    level = raw[L9_LEVEL_INDEX]
    if level > 100:
        return None
    return level, raw[L9_CHARGE_INDEX] != 0


# ---------------- HERO 68 ----------------
def hero_query(command: int, param: int, length: int) -> bytes:
    packet = bytearray(HERO_PACKET + 1)
    packet[0] = HERO_RID
    packet[1] = command
    packet[2] = param
    packet[4] = 1
    packet[6] = length
    packet[-1] = (255 - (sum(packet) & 0xFF)) & 0xFF
    return bytes(packet)


def hero_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def hero_is_response(packet: bytes, command: int, param: int, length: int) -> bool:
    return (len(packet) == HERO_PACKET and packet[0] == command and packet[1] == param
            and packet[2] == 0 and packet[3] == 1 and packet[4] == 0
            and packet[5] == length
            and ((hero_checksum(packet) + HERO_RID) & 0xFF) == 0xFF)


def hero_is_device(packet: bytes) -> bool:
    return hero_is_response(packet, 0x82, 1, 6) and \
        packet[6:12] == bytes([0x12, 0, 0, 0, 0, 0x0A])


def hero_parse_battery(packet: bytes):
    if not hero_is_response(packet, 0x87, 0, 2):
        return None
    percent = packet[6]
    if percent > 100:
        return None
    flag = packet[7]
    if flag & 0xF0:
        return percent, True
    if flag & 0x0F:
        return percent, False                # 已充满
    return percent, False


def hero_fragment(raw: bytes):
    """解析 20 字节分片 → (total, current, sync, payload) 或 None。"""
    if len(raw) != HERO_REPORT or raw[0] != HERO_RID or raw[1] != 0x66:
        return None
    total = raw[2] & 0x7F
    current = raw[3] & 0x7F
    length = raw[4] & 0x7F
    sync = ((raw[2] & 0x80) >> 5) | ((raw[3] & 0x80) >> 6) | ((raw[4] & 0x80) >> 7)
    if not (1 <= total <= 5 and 1 <= current <= total and length <= HERO_FRAG_PAYLOAD):
        return None
    if raw[5 + length] != hero_checksum(raw[1:5 + length]):
        return None
    return total, current, sync, bytes(raw[5:5 + length])


def hero_ack(fragment: bytes) -> bytes:
    ack = bytearray(HERO_REPORT)
    ack[:5] = fragment[:5]
    ack[4] &= 0x80
    ack[5] = hero_checksum(bytes(ack[1:5]))
    return bytes(ack)


def hero_collect(dev, ms: int):
    """收满一个 63 字节包；期间给每个分片回 ACK。"""
    pending = bytearray()
    total = current = sync = 0
    deadline_ms = ms
    while deadline_ms > 0:
        raw = base.read(dev, 120, HERO_REPORT)
        deadline_ms -= 120
        if raw is None:
            continue
        frag = hero_fragment(raw)
        if frag is not None:
            frag_total, frag_current, frag_sync, payload = frag
            if frag_current == 1:
                pending = bytearray()
                total, current, sync = frag_total, 0, 0
            if frag_total != total or frag_current != current + 1:
                continue
            if frag_current > 1 and frag_sync != ((sync + 1) & 7):
                continue
            pending.extend(payload)
            current, sync = frag_current, frag_sync
            base.write(dev, hero_ack(raw))
            if current != total:
                continue
            if len(pending) == HERO_PACKET:
                return bytes(pending)
            pending = bytearray()
            continue
        if len(raw) == HERO_PACKET + 1 and raw[0] == HERO_RID:
            return bytes(raw[1:])
        if len(raw) == HERO_PACKET:
            return bytes(raw)
    return None


# ---------------- 入口 ----------------
def _model(ctx: Ctx) -> str:
    if ctx.pid == G9_PID:
        return "狼蛛 G9"
    if ctx.pid == L9_PID:
        return "狼蛛 L9 Ultra"
    if ctx.pid == HERO_PID:
        return "AULA HERO 68 Air"
    return "AULA F99 Pro"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _targets(ctx)
    if not targets:
        return None
    key = ("aula", ctx.phys)
    if base.cooled(key, force):
        return None

    kind = base.KEYBOARD if ctx.pid in (F99_PID, HERO_PID) else \
        (base.HEADSET if ctx.pid == G9_PID else base.MOUSE)

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            if ctx.pid == G9_PID:
                hit = base.wait_for(dev, g9_parse, ms=2200)
            elif ctx.pid == L9_PID:
                base.drain(dev)
                if not base.write(dev, l9_query(_io(member)[1])):
                    continue
                hit = base.wait_for(dev, l9_parse, ms=1300)
            elif ctx.pid == HERO_PID:
                hit = _hero_probe(dev)
            else:
                hit = _f99_probe(dev)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·狼蛛",
                           model=_model(ctx), kind=kind)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None


def _f99_probe(dev):
    base.drain(dev)
    if not base.write(dev, v1_frame(V1_SESSION, 0x01)):
        return None
    session_read = None
    model_ok = False
    for _ in range(4):                       # 约 1.2 秒
        raw = base.read(dev, 300, V1_FRAME)
        if raw is None:
            continue
        code = v1_model_code(raw)
        if code is not None:
            if code != F99_MODEL:
                return None                  # 别的型号（迈从 G75 / 凌豹 K98）让位
            model_ok = True
            continue
        hit = v1_read(raw)
        if hit is not None and session_read is None:
            session_read = hit
    if session_read is not None:
        return session_read

    for _ in range(2):
        if not base.write(dev, v1_frame(V1_QUERY, 0x01)):
            continue
        for _ in range(4):
            raw = base.read(dev, 300, V1_FRAME)
            if raw is None:
                continue
            if v1_model_code(raw) == F99_MODEL:
                model_ok = True
                continue
            hit = v1_read(raw)
            if hit is not None:
                return hit
    return None


def _hero_probe(dev):
    base.drain(dev)
    if not base.write(dev, hero_query(0x82, 0x01, 6)):
        return None
    packet = hero_collect(dev, 1500)
    if packet is None or not hero_is_device(packet):
        return None

    if not base.write(dev, hero_query(0x87, 0x00, 2)):
        return None
    packet = hero_collect(dev, 1500)
    if packet is None:
        return None
    return hero_parse_battery(packet)
