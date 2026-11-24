# -*- coding: utf-8 -*-
"""【键盘】华硕 ROG Strix Scope II 96 Wireless（Omni 接收器）

适配设备
    ROG Strix Scope II 96 Wireless    0B05:1ACE（Omni 接收器）
    配对的键盘型号必须在 0x1AAE / 0x1AAF / 0x1AB0 之内。

怎么认
    这条链路要走两步，缺一步就会读错设备：
    1. 先在**控制接口**（report 1）发 `A0` 配对查询，应答里的配对表必须含
       这台键盘的型号 —— Omni 接收器可以换接好几只设备，只按 VID:PID 认领
       会把别人的键盘报成 Scope；
    2. 配对了才在键盘接口（report 2）发 `12 01` 读电量。
    因为配对表与电量分处两个接口，本模块声明 `ALL = True`：扫描时会把同一
    VID:PID 的所有接口并进同一个 ctx。

怎么读
    配对表应答：计数 [3]，从 [5] 起每 4 字节一条（PID 低/高、report、长度）。
    电量应答：`[0]=2 [1]=0x12 [2]=1 [6]=电量 [9]=充电`

注意
    华硕的无线耳机（0B05:1AFA）在 headset/asus.py，是另一条直连链路。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading
from providers import hidreports

VID = 0x0B05
KB_PID = 0x1ACE
SCOPE_PIDS = (0x1AAE, 0x1AAF, 0x1AB0)

# Omni 接收器上"配对表"在控制接口、电量在键盘接口 —— 必须把同一 VID:PID
# 的所有接口并成一个 ctx 才读得到，不能按接口分家。
ALL = True
LABEL = "华硕"

KB_REPORT = 2
CTRL_REPORT = 1
GROUP_READ = 0x12


def match(ctx: Ctx) -> bool:
    if ctx.vid != VID or ctx.pid != KB_PID:
        return False
    return bool(_keyboard_member(ctx) or _control_member(ctx))


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
    if len(raw) != 64 or raw[0] != KB_REPORT or raw[1] != GROUP_READ or raw[2] != 1:
        return None
    if raw[6] > 100 or raw[9] > 1:
        return None
    return raw[6], raw[9] == 1


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
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
        hit = _query(dev, _frame(KB_REPORT, GROUP_READ, 1), _parse_battery)
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
