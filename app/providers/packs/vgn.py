# -*- coding: utf-8 -*-
"""VGN 三套协议：蜻蜓 F1 V5 Turbo+（kc2）、蜻蜓 F2 大师+（y2）、V98 Pro 键盘。

1) kc2 — 391D:1A23（接收器）/ 391D:1026（有线本体），0xFFC1/1，64/64
   请求 `B3 06` + 62 个 0；应答 payload[0] = 0x06，
   电量在 payload[19]（bit7 = 充电、低 7 位 = 百分比）。
   门槛：payload 里至少 3 个非零字节才认，挡掉"读失败返回全零缓冲"。

2) y2 — 3554:FB56（接收器）/ FB57（有线），0xFF02/2，**恰好** 17/17
   请求 `08 04`，校验 = (85 − 前 15 字节之和 − reportId) & 0xFF
   应答 payload[5] = 电量（0 与 >100 都判无效）、[6] = 充电、[7..8] = 电压 mV。
   长度必须精确相等：同 VID 下 F99 Pro 是 20/20，放宽会把 17 字节帧灌进 20 字节通道。

3) V98 Pro — 320F:5088，0xFF1C/0x0092，输出 ≥17
   请求 `04 00 00 1A 06 00 00 00`；应答 [0]=0x04、[3]=0x1A 才算电量帧，
   电量在 [8]、充电在 [9]。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

# kc2
KC2_VID = 0x391D
KC2_PIDS = (0x1A23, 0x1026)
KC2_PAGE = 0xFFC1
KC2_USAGE = 0x0001
KC2_RID = 0xB3
KC2_CMD = 0x06
KC2_LEN = 64
KC2_LEVEL = 19
KC2_CHARGE_BIT = 0x80

# y2
Y2_VID = 0x3554
Y2_PIDS = (0xFB56, 0xFB57)
Y2_PAGE = 0xFF02
Y2_USAGE = 0x0002
Y2_RID = 0x08
Y2_CMD = 0x04
Y2_PAYLOAD = 16
Y2_LEN = 17
Y2_SEED = 85

# V98 Pro
V98_VID = 0x320F
V98_PID = 0x5088
V98_PAGE = 0xFF1C
V98_USAGE = 0x0092
V98_RID = 0x04
V98_QUERY = bytes([0x00, 0x00, 0x1A, 0x06, 0x00, 0x00, 0x00])


def match(ctx: Ctx) -> bool:
    if _is_kc2(ctx) or _is_y2(ctx) or _is_v98(ctx):
        return True
    return False


def _io(member) -> tuple[int, int]:
    from providers import hidreports
    try:
        reports = hidreports.reports(member.get("path"))
    except Exception:
        return 0, 0
    ins = reports.get("in", {}).values()
    outs = reports.get("out", {}).values()
    return max(ins, default=0), max(outs, default=0)


def _is_kc2(ctx: Ctx) -> bool:
    if ctx.vid != KC2_VID or ctx.pid not in KC2_PIDS:
        return False
    targets = ctx.pick(page_=KC2_PAGE, usage_=KC2_USAGE)
    return any(min(_io(m)) >= KC2_LEN for m in targets)


def _is_y2(ctx: Ctx) -> bool:
    if ctx.vid != Y2_VID or ctx.pid not in Y2_PIDS:
        return False
    targets = ctx.pick(page_=Y2_PAGE, usage_=Y2_USAGE)
    return any(_io(m) == (Y2_LEN, Y2_LEN) for m in targets)


def _is_v98(ctx: Ctx) -> bool:
    if ctx.vid != V98_VID or ctx.pid != V98_PID:
        return False
    targets = ctx.pick(page_=V98_PAGE, usage_=V98_USAGE)
    if not any(_io(m)[1] >= Y2_LEN for m in targets):
        return False
    # 320F:5088 这个 dongle 号段被 VGN 多款键盘共用（V98 Pro / VXE75 系）。
    # 0xFF1C/0x0092 接口和报文长度它们都一样，只看指纹会把 VXE75 也认成 V98 Pro，
    # 于是同一只接收器出现两行、名字还不一样。所以要求产品名自证；
    # 名字读不到（少数 dongle 不回 product_string）时按接口认，不做二次猜测。
    name = (ctx.name or "").upper()
    if "V98" in name:
        return True
    if "VXE" in name or "VGN" in name:
        return False                     # 明确是别的型号（如 VXE75），让给 Evision
    return True                          # 读不到产品名时按接口认，不做二次猜测


# ---------------- kc2 ----------------
def build_kc2() -> bytes:
    frame = bytearray(KC2_LEN)
    frame[0] = KC2_RID
    frame[1] = KC2_CMD
    return bytes(frame)


def parse_kc2(raw: bytes):
    for start in (1, 0):
        if len(raw) < start + KC2_LEVEL + 1:
            continue
        if raw[start] != KC2_CMD:
            continue
        non_zero = sum(1 for byte in raw[start + 1:start + 41] if byte)
        if non_zero < 3:
            continue                        # 全零缓冲 = 没读到
        packed = raw[start + KC2_LEVEL]
        percent = packed & 0x7F
        if percent > 100:
            continue
        charging = bool(packed & KC2_CHARGE_BIT)
        return percent, charging
    return None


# ---------------- y2 ----------------
def y2_checksum(payload: bytes, report_id: int = Y2_RID) -> int:
    return (Y2_SEED - (sum(payload[:Y2_PAYLOAD - 1]) & 0xFF) - report_id) & 0xFF


def build_y2() -> bytes:
    frame = bytearray(Y2_LEN)
    frame[0] = Y2_RID
    frame[1] = Y2_CMD
    frame[-1] = y2_checksum(frame[1:])
    return bytes(frame)


def parse_y2(raw: bytes):
    starts = (1, 0) if len(raw) >= Y2_LEN and raw[0] == Y2_RID else (0,)
    for start in starts:
        if len(raw) < start + Y2_PAYLOAD:
            continue
        payload = raw[start:start + Y2_PAYLOAD]
        if payload[0] != Y2_CMD or payload[1] != 0:
            continue
        if payload[-1] != y2_checksum(payload):
            continue
        percent = payload[5]
        if percent == 0 or percent > 100:
            continue
        return percent, payload[6] == 1
    return None


# ---------------- V98 Pro ----------------
def build_v98(length: int) -> bytes:
    frame = bytearray(max(length, len(V98_QUERY) + 1))
    frame[0] = V98_RID
    frame[1:1 + len(V98_QUERY)] = V98_QUERY
    return bytes(frame)


def parse_v98(raw: bytes):
    if len(raw) <= 9:
        return None
    if raw[0] != V98_RID or raw[3] != 0x1A:
        return None
    percent = raw[8]
    if percent > 100:
        return None
    return percent, raw[9] != 0


def _model(ctx: Ctx) -> str:
    name = (ctx.name or "").replace("VGN", "").strip()
    if _is_v98(ctx):
        return "VGN V98 Pro"
    if _is_y2(ctx):
        return "VGN 蜻蜓 F2 大师+"
    return "VGN 蜻蜓 F1 V5 Turbo+"


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    key = ("vgn", ctx.phys)
    if base.cooled(key, force):
        return None

    plan = []
    if _is_v98(ctx):
        plan = [(m, "v98") for m in ctx.pick(page_=V98_PAGE, usage_=V98_USAGE)]
    elif _is_y2(ctx):
        plan = [(m, "y2") for m in ctx.pick(page_=Y2_PAGE, usage_=Y2_USAGE)]
    elif _is_kc2(ctx):
        plan = [(m, "kc2") for m in ctx.pick(page_=KC2_PAGE, usage_=KC2_USAGE)]

    for member, kind in plan[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if kind == "v98":
                length = _io(member)[1]
                if not base.write(dev, build_v98(length)):
                    continue
                hit = base.wait_for(dev, parse_v98, ms=900, size=max(length, 17))
                kind_name = base.KEYBOARD
            elif kind == "y2":
                if not base.write(dev, build_y2()):
                    continue
                hit = base.wait_for(dev, parse_y2, ms=900, size=Y2_LEN)
                kind_name = base.MOUSE
            else:
                if not base.write(dev, build_kc2()):
                    continue
                hit = base.wait_for(dev, parse_kc2, ms=900, size=KC2_LEN)
                kind_name = base.MOUSE
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·VGN",
                           model=_model(ctx), kind=kind_name)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
