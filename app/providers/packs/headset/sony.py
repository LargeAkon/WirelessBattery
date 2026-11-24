# -*- coding: utf-8 -*-
"""【耳机】索尼 INZONE H9 II 接收器

适配设备
    索尼 INZONE H9 II    054C:0FA8 接收器，0xFF04 控制传输查询

怎么读
    64 字节帧，输入输出共用 report ID 0x02：
        查询 `02 0C 01 00 FC 08 96 C3 41 04 01 01 00 A0 …`（末位 0xA0 = 0x9C + 命令号）
        应答 `[8]=0x14 [9]=0x04 [10]=0x10(应答)/0xA0(通知) [13]=充电 [14]=电量`

注意
    必须走控制传输 SET_REPORT（HidD_SetOutputReport）；写中断 OUT 端点时设备
    只回显，会把回显当成真读数 —— 这是参考项目用一整晚换来的教训。
    本工具只做 2.4G：DualSense 那条走蓝牙 HID，不接。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

SONY_VID = 0x054C
H9_PID = 0x0FA8

H9_PAGE = 0xFF04
H9_RID = 0x02
H9_LEN = 64
CLASS_STATUS = 0x41
CMD_BATTERY = 0x04
RESP_CLASS = 0x14
FLAG_RESPONSE = 0x10
FLAG_NOTIFY = 0xA0


def match(ctx: Ctx) -> bool:
    if ctx.vid != SONY_VID or ctx.pid != H9_PID:
        return False
    return any(_out_len(m) == H9_LEN for m in ctx.pick(page_=H9_PAGE))


def _out_len(member) -> int:
    from providers import hidreports
    try:
        outs = hidreports.reports(member.get("path")).get("out", {})
    except Exception:
        return 0
    return max(outs.values()) if outs else 0


def build_h9() -> bytes:
    frame = bytearray(H9_LEN)
    frame[0] = H9_RID
    frame[1] = 0x0C
    frame[2] = 0x01
    frame[4] = 0xFC
    frame[5] = 0x08
    frame[6] = 0x96
    frame[7] = 0xC3
    frame[8] = CLASS_STATUS
    frame[9] = CMD_BATTERY
    frame[10] = 0x01
    frame[11] = 0x01
    frame[13] = (0x9C + CMD_BATTERY) & 0xFF
    return bytes(frame)


def parse_h9(raw: bytes):
    if raw is None or len(raw) < H9_LEN:
        return None
    if raw[0] != H9_RID or raw[8] != RESP_CLASS or raw[9] != CMD_BATTERY:
        return None
    if raw[10] not in (FLAG_RESPONSE, FLAG_NOTIFY):
        return None
    percent = raw[14]
    if percent > 100:
        return None
    charge = raw[13]
    if charge == 0:
        return percent, False
    if charge == 1:
        return percent, True
    return percent, None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    key = ("sony", ctx.phys)
    if base.cooled(key, force):
        return None

    targets = ctx.pick(page_=H9_PAGE)
    try:
        from providers import hidctl
    except Exception:
        hidctl = None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if hidctl is None or not hidctl.set_output_report(member.get("path"), build_h9()):
                continue
            hit = base.wait_for(dev, parse_h9, ms=1200, size=H9_LEN)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·索尼",
                           model="索尼 INZONE H9 II", kind=base.HEADSET)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
