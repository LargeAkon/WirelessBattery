# -*- coding: utf-8 -*-
"""【键盘】狼蛛 AULA F99 Pro、AULA HERO 68 Air

适配设备
    AULA F99 Pro       3554:FA09，接口 0xFF02/0x0002，20/20 字节
    AULA HERO 68 Air   372E:106C，接口 0xFF60/0x0061，20/20，report 0x09

怎么认
    F99 Pro 与凌豹 K98、迈从 G75 共用 3554:FA09，HID 层完全同指纹，
    只能靠会话 ACK 的型号码分流：F99 Pro = 0x0158，不是就立刻让位。
    HERO 68 靠 Bytech 8K 分片协议自证：先查 UUID，6 字节必须是
    `12 00 00 00 00 0A` 才认。

怎么读
    F99 Pro：发 `13 05 01` 开会话，等 ACK 或 0A 电量推送（type 0x05、电量 [6]、
             标志 [7]，标志 bit4 = 充电）；没读到再发 `13 4A 01` 查询。
             会话帧与解析见 keyboard/_compx.py。
    HERO 68：`82 01` 查 UUID → `87 00` 查电量，应答 [6] = 电量、
             [7] 高 4 位 = 充电、低 4 位 = 已充满。响应被拆成 20 字节分片时
             要逐片回 ACK，否则设备不发下一片。

注意
    狼蛛的耳机 G9 在 headset/aula.py，鼠标 L9 Ultra 在 mouse/aula.py。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading
from providers.packs.keyboard import _compx

# F99 Pro
F99_MODEL = 0x0158

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
    if ctx.vid == _compx.VID and ctx.pid == _compx.PID:
        return bool(_compx.targets(ctx))
    if ctx.vid == HERO_VID and ctx.pid == HERO_PID:
        return bool(_hero_targets(ctx))
    return False


# ---------------- F99 Pro ----------------
def _f99_probe(dev):
    base.drain(dev)
    if not base.write(dev, _compx.frame(_compx.SESSION, 0x01)):
        return None
    session_read = None
    for _ in range(4):                       # 约 1.2 秒
        raw = base.read(dev, 300, _compx.LEN)
        if raw is None:
            continue
        code = _compx.model_code(raw)
        if code is not None:
            if code != F99_MODEL:
                return None                  # 别的型号（迈从 G75 / 凌豹 K98）让位
            continue
        hit = _compx.read(raw)
        if hit is not None and session_read is None:
            session_read = hit
    if session_read is not None:
        return session_read

    for _ in range(2):
        if not base.write(dev, _compx.frame(_compx.QUERY, 0x01)):
            continue
        for _ in range(4):
            raw = base.read(dev, 300, _compx.LEN)
            if raw is None:
                continue
            if _compx.model_code(raw) == F99_MODEL:
                continue
            hit = _compx.read(raw)
            if hit is not None:
                return hit
    return None


# ---------------- HERO 68 Air ----------------
def _hero_targets(ctx: Ctx) -> list[dict]:
    out = []
    for member in ctx.pick(page_=HERO_PAGE, usage_=HERO_USAGE):
        ins, outs = base.io_lengths(member)
        if ins == HERO_REPORT and outs == HERO_REPORT:
            out.append(member)
    return out


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


# ---------------- 入口 ----------------
def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    is_hero = ctx.vid == HERO_VID and ctx.pid == HERO_PID
    if is_hero:
        targets = _hero_targets(ctx)
        label, model = "协议包·狼蛛", "AULA HERO 68 Air"
    else:
        targets = _compx.targets(ctx)
        label, model = "协议包·狼蛛", "AULA F99 Pro"
    if not targets:
        return None

    key = ("aula-kb", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            hit = _hero_probe(dev) if is_hero else _f99_probe(dev)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label=label, model=model,
                           kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
