# -*- coding: utf-8 -*-
"""【键盘】凌豹 LINGBAO K98

适配设备
    凌豹 K98        3554:FA09，接口 0xFF02/0x0002，20/20 字节

怎么认
    这个 VID:PID 被三家的键盘共用：AULA F99 Pro、凌豹 K98、迈从 G75。
    HID 层完全同指纹，只能靠**会话 ACK 里的型号码**分流（K98 = 0x0212）。
    同一只接收器上，keyboard/aula.py、本文件、keyboard/mchose.py 会依次尝试，
    谁的型号对上谁认领，其余主动让位。

怎么读
    会话帧 `13 05 01`，之后解析 0A 电量推送或 4A 查询应答；
    会话期没读到就再发一次 `13 4A 01` 查询。
    帧构造与解析在 keyboard/_compx.py（三家共用）。

注意
    型号码不是 0x0212 就立刻让位，绝不拿别人的帧报电量 —— 否则会把
    F99 Pro 的读数挂到 K98 名下。
    凌豹的鼠标 M5PRO Max（3151:402D）在 mouse/lingbao.py。
"""
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading
from providers.packs.keyboard import _compx

MODEL_CODE = 0x0212


def match(ctx: Ctx) -> bool:
    if ctx.vid != _compx.VID or ctx.pid != _compx.PID:
        return False
    return bool(_compx.targets(ctx))


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = _compx.targets(ctx)
    if not targets:
        return None
    key = ("lingbao-k98", ctx.phys)
    if base.cooled(key, force):
        return None

    for member in targets[:1]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)
            if not base.write(dev, _compx.frame(_compx.SESSION, 0x01)):
                continue
            session_read = None
            matched = False
            for _ in range(4):
                raw = base.read(dev, 300, _compx.LEN)
                if raw is None:
                    continue
                code = _compx.model_code(raw)
                if code is not None:
                    if code != MODEL_CODE:
                        break                # 是 F99 Pro / G75：让位
                    matched = True
                    continue
                hit = _compx.read(raw)
                if hit is not None and session_read is None:
                    session_read = hit
            if not matched:
                continue
            if session_read is not None:
                base.clear_fail(key)
                return Reading(session_read[0], session_read[1],
                               label="协议包·凌豹", model="凌豹 K98",
                               kind=base.KEYBOARD)
            for _ in range(2):
                if not base.write(dev, _compx.frame(_compx.QUERY, 0x01)):
                    continue
                for _ in range(4):
                    raw = base.read(dev, 300, _compx.LEN)
                    if raw is None:
                        continue
                    hit = _compx.read(raw)
                    if hit is not None:
                        base.clear_fail(key)
                        return Reading(hit[0], hit[1], label="协议包·凌豹",
                                       model="凌豹 K98", kind=base.KEYBOARD)
        except Exception:
            continue
        finally:
            base.close(dev)
    base.mark_fail(key)
    return None
