# -*- coding: utf-8 -*-
"""华硕 ROG：Omni 接收器上的 Scope II 96 键盘 + 0x1AFA 无线耳机。

键盘这条要两步，缺一步就会读错设备：
1. 先在**控制接口**（report 1）发 `A0` 配对查询，应答里那份配对表必须
   含这台键盘的型号（0x1AAE / 0x1AAF / 0x1AB0）—— Omni 接收器可以换接
   好几只设备，只按 VID:PID 认领会把别人的键盘报成 Scope；
2. 配对了才在键盘接口（report 2）发 `12 01` 读电量。

耳机（0x1AFA）是直连，没有配对表，靠 PID 白名单兜住：`12 07` 取电量、
`12 08` 取充电位。两条帧先后等应答，不重试；充电帧没回音只丢充电位。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading
from providers import hidreports

VID = 0x0B05
KB_PID = 0x1ACE
HEADSET_PID = 0x1AFA
SCOPE_PIDS = (0x1AAE, 0x1AAF, 0x1AB0)

# Omni 接收器上"配对表"在控制接口、电量在键盘接口 —— 必须把同一 VID:PID
# 的所有接口并成一个 ctx 才读得到，不能按接口分家。
ALL = True
LABEL = "华硕"

KB_REPORT = 2
CTRL_REPORT = 1
HS_REPORT = 0xCC
GROUP_READ = 0x12
CMD_POWER = 0x07
CMD_CHARGING = 0x08


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID:
        return False
    if ctx.pid == HEADSET_PID:
        return True
    if ctx.pid == KB_PID:
        return bool(_keyboard_member(ctx) or _control_member(ctx))
    return False


def _keyboard_member(ctx: Ctx):
    for m in ctx.pick(page_=0xFF00, usage_=1):
        if "&mi_02&col02#" in base.path_text(m).lower():
            return m
        if hidreports.has_report(m.get("path"), "out", KB_REPORT):
            return m
    return None


def _control_member(ctx: Ctx):
    for m in ctx.pick(page_=0xFF00, usage_=1):
        if m is _keyboard_member(ctx):
            continue
        if hidreports.has_report(m.get("path"), "out", CTRL_REPORT, 64):
            return m
    return None


def _receiver_key(path: str) -> str | None:
    parts = path.split("#")
    if len(parts) < 4:
        return None
    col = parts[1].lower().find("&col")
    inst = parts[2].rfind("&")
    if col < 0 or inst < 0:
        return None
    return parts[1][:col] + "#" + parts[2][:inst]


def _query(dev, frame: bytes, matches, ms: int = 700, size: int = 64):
    base.drain(dev)
    if not base.write(dev, frame):
        return None
    return base.wait_for(dev, matches, ms=ms, size=size)


def _frame(report_id: int, command: int, sub: int = 0) -> bytes:
    frame = bytearray(64)
    frame[0] = report_id
    frame[1] = command
    frame[2] = sub
    return bytes(frame)


def _parse_paired(raw: bytes):
    """配对表应答：计数 [3]，从 [5] 起每 4 字节一条（PID 低/高、report、长度）。"""
    if len(raw) != 64 or raw[0] != 1 or raw[1] != 0xA0 or raw[2] != 0 or raw[4] != 0:
        return None
    count = raw[3]
    if count > (64 - 5) // 4:
        return None
    found = None
    for i in range(count):
        at = 5 + i * 4
        pid = raw[at] | (raw[at + 1] << 8)
        if raw[at + 2] != KB_REPORT:
            continue
        if found is not None or raw[at + 3] != 4 or pid not in SCOPE_PIDS:
            return None
        found = pid
    return found


def _parse_battery(raw: bytes):
    if len(raw) != 64 or raw[0] != KB_REPORT or raw[1] != 0x12 or raw[2] != 1:
        return None
    if raw[6] > 100 or raw[9] > 1:
        return None
    return raw[6], raw[9] == 1


def _parse_headset(command: int):
    def parse(raw: bytes):
        if len(raw) < 6 or raw[0] != HS_REPORT or raw[1] != GROUP_READ or raw[2] != command:
            return None
        return raw[5:]
    return parse


def _headset(ctx: Ctx, force: bool) -> Reading | None:
    targets = ctx.pick(page_=0xFF00, usage_=1)
    if not targets:
        return None
    key = ("asus-hs", ctx.phys)
    if base.cooled(key, force):
        return None
    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            data = _query(dev, _frame(HS_REPORT, GROUP_READ, CMD_POWER),
                          _parse_headset(CMD_POWER))
            if data is None or len(data) < 4:
                continue
            percent = data[1]
            if percent == 0xFE or percent > 100:
                continue
            charging_frame = _query(dev, _frame(HS_REPORT, GROUP_READ, CMD_CHARGING),
                                    _parse_headset(CMD_CHARGING))
            charging = None
            if charging_frame:
                charging = charging_frame[0] == 1
            base.clear_fail(key)
            return Reading(percent, charging, label="协议包·华硕",
                           model=_headset_name(ctx), kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None


def _headset_name(ctx: Ctx) -> str:
    name = (ctx.name or "").strip()
    if not name or name.isupper() or name.lower().startswith("usb"):
        return "华硕 ROG 耳机"
    return f"华硕 {name}"


def _keyboard(ctx: Ctx, force: bool) -> Reading | None:
    keyboard = _keyboard_member(ctx)
    control = _control_member(ctx)
    if keyboard is None or control is None:
        return None
    key = ("asus-kb", ctx.phys)
    if base.cooled(key, force):
        return None

    # 1) 配对核对：控制接口的 report 1 发 A0
    dev = None
    try:
        dev = base.open_member(control)
        paired = _query(dev, _frame(CTRL_REPORT, 0xA0, 0), _parse_paired)
        if not paired:
            base.mark_fail(key)
            return None
    except Exception:
        base.mark_fail(key)
        return None
    finally:
        base.close(dev)

    # 2) 键盘接口 report 2 读电量
    dev = None
    try:
        dev = base.open_member(keyboard)
        hit = _query(dev, _frame(KB_REPORT, 0x12, 1), _parse_battery)
        if hit is None:
            base.mark_fail(key)
            return None
        base.clear_fail(key)
        percent, charging = hit
        return Reading(percent, charging, label="协议包·华硕",
                       model="ROG Strix Scope II 96 Wireless", kind=base.KEYBOARD)
    except Exception:
        base.mark_fail(key)
        return None
    finally:
        base.close(dev)


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    if ctx.pid == HEADSET_PID:
        return _headset(ctx, force)
    if ctx.pid == KB_PID:
        return _keyboard(ctx, force)
    return None
