# -*- coding: utf-8 -*-
"""协议包：从 vigil-watt 移植过来的厂商协议。

一个家族 = 一个模块，暴露三个东西：
    match(ctx)  -> bool         只看接口指纹，不做 I/O（除了读描述符，已缓存）
    probe(ctx, force) -> Reading | None
    ALL = True                  可选：需要把同一 VID:PID 的**所有接口**放进
                                同一个 ctx（华硕 Omni 接收器要在控制接口上
                                核对配对表，电量却在键盘接口上）

调用顺序按 PACKS 顺序来，命中一条就停 —— 同一只接收器上的多套协议里，
先验证过的那条优先。
"""
from __future__ import annotations

import time

from model import Device
from providers import hidlist
from providers.hidpath import is_bluetooth, phys_token
from providers.packs import (
    ajazz, akg, asus, atk, aula, base, betop, cherry, darkrim, eweadn, gamesir,
    ganss, haute, hecate, hyperx_cf2, inphic_delux, lingbao, mchose, mojhon,
    pulsar, rapoo, razer, sony, thunderobot, vgn,
)

# 顺序 = 优先级。被动听/轻查询的排前面，要发多条帧的排后面。
# 共用 VID:PID 的家族（3554:FA09 的 AULA / 凌豹 / 迈从）靠"先试谁能自证"排序：
# 先试的会在型号/固件不符时主动让位。
# 本工具只做 2.4G 与 USB 有线：蓝牙链路（如 DualSense 蓝牙报告）一律不接。
PACKS = (
    inphic_delux,       # 1D57:FA65 被动
    hecate,             # 35BB:D00B 被动 + 一条查询
    rapoo,              # 24AE 被动 0x07 状态帧
    hyperx_cf2,         # 03F0:0AC1 被动状态流
    aula,               # 3554:FA09 / 38A6 G9 被动 + L9 查询 + HERO 68 分片
    darkrim,            # 3654:6901 GetBasicInfo
    gamesir,            # 3537 心跳 + 状态流
    cherry,             # 046A 块读
    pulsar,             # 3554:F508 17 字节
    ajazz,              # 3151:4011 feature F7
    lingbao,            # 3151:402D feature F7 + 3554:FA09 K98 会话
    thunderobot,        # 369B:0234 TLV
    eweadn,             # 0C45:FEFE / 372E:1026
    asus,               # 0B05:1ACE / 1AFA
    razer,              # 1532 四条链路
    mchose,             # 3837 七条链路 + 3554:FA09 共用指纹
    vgn,                # 391D / 3554:FB56 / 320F
    atk,                # 373B 鼠标 17 字节 + VIA 键盘
    betop,              # 20BC / 20DD
    ganss,              # 05AC:024F 33 字节
    akg,                # 0ECB:20D9 RACE
    haute,              # 054C:0CE6 适配器（只读 feature，不做蓝牙）
    sony,               # 054C:0FA8 INZONE H9 II 接收器
    mojhon,             # E2B7 A5 寄存器
)

# 整个通道的预算。超了就不再开新设备：宁可这一轮少认一台，
# 也不要把一次刷新拖成十几秒。
BUDGET_S = 9.0


def _instance(path) -> str:
    token = phys_token(path)
    if "&" in token:
        return token.rsplit("&", 1)[0]
    return token


def _name_of(members: list[dict], vid: int, pid: int) -> str:
    generic = ("usb receiver", "2.4g receiver", "2.4g dongle", "wireless receiver",
               "receiver", "dongle", "hid-compliant", "usb 输入设备")
    for info in members:
        product = (info.get("product_string") or "").strip()
        if product and not any(w in product.lower() for w in generic):
            return product
    for info in members:
        product = (info.get("product_string") or "").strip()
        if product:
            return product
    return f"无线设备 {vid:04X}:{pid:04X}"


def scan(debug: list | None = None, force: bool = False) -> list[Device]:
    if base.hid is None:
        return []
    infos = hidlist.devices()

    per_instance: dict[tuple, list[dict]] = {}
    per_vid_pid: dict[tuple, list[dict]] = {}
    for info in infos:
        path = info.get("path")
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not path or not vid or is_bluetooth(path):
            continue
        per_instance.setdefault((vid, pid, _instance(path)), []).append(info)
        per_vid_pid.setdefault((vid, pid), []).append(info)

    found: dict[str, Device] = {}
    started = time.monotonic()

    for (vid, pid, phys), members in per_instance.items():
        if time.monotonic() - started > BUDGET_S:
            break
        name = _name_of(members, vid, pid)
        ctx = base.Ctx(vid=vid, pid=pid, phys=phys, members=members, name=name)
        for module in PACKS:
            if getattr(module, "ALL", False):
                continue                     # 已经按 VID:PID 合组试过
            if not _safe_match(module, ctx):
                continue
            reading = _safe_probe(module, ctx, force, debug)
            if reading is not None and reading.percent is not None:
                device = base.emit(ctx, reading)
                found[device.key] = device
                break

    # 华硕这类要跨接口的家族：把同 VID:PID 的所有接口并成一个 ctx 再试一次
    for (vid, pid), members in per_vid_pid.items():
        if time.monotonic() - started > BUDGET_S:
            break
        modules = [m for m in PACKS if getattr(m, "ALL", False)]
        if not modules:
            continue
        phys = _instance(members[0].get("path"))
        ctx = base.Ctx(vid=vid, pid=pid, phys=phys, members=members,
                       name=_name_of(members, vid, pid))
        for module in modules:
            if not _safe_match(module, ctx):
                continue
            reading = _safe_probe(module, ctx, force, debug)
            if reading is not None and reading.percent is not None:
                device = base.emit(ctx, reading)
                found[device.key] = device
                break

    devices = list(found.values())
    if debug is not None:
        debug.append(f"[协议包] 命中 {len(devices)} 台")
    return devices


_OWNS: dict[tuple, tuple[float, bool]] = {}
_OWNS_TTL = 30.0
_OWNS_MAX = 64


def owns(vid: int, pid: int, members: list[dict], phys: str = "") -> bool:
    """这组接口是否已被某个协议包认领（只看判据，不做 I/O）。

    旧通道（芯片组/协议库）用它提前让位：同一只接收器被两套代码同时打开时，
    谁先读走应答帧谁就赢，另一套必然读到半截——两套都"偶尔能读到"比一套读不到更难查。

    判据只依赖接口指纹与产品名，短时间内不会变；而芯片组和协议库两条通道都会
    各问一遍，所以这里缓存 30 秒，一轮扫描里 24 个模块的判据只跑一次。
    """
    # 名字要带上：320F:5088 这类号段上多款键盘共用同一套指纹，
    # 只有产品名能区分 V98 Pro 与 VXE75。空名字会让判据退化成"按接口认"，
    # 于是旧通道被误判成"已被接管"而整组跳过。
    name = _name_of(members, vid, pid)
    cache_key = (vid, pid, phys or "", name)
    now = time.monotonic()
    hit = _OWNS.get(cache_key)
    if hit is not None and now - hit[0] < _OWNS_TTL:
        return hit[1]

    ctx = base.Ctx(vid=vid, pid=pid, phys=phys or "", members=members, name=name)
    value = any(_safe_match(module, ctx) for module in PACKS)
    if len(_OWNS) >= _OWNS_MAX:
        _OWNS.clear()
    _OWNS[cache_key] = (now, value)
    return value


def _safe_match(module, ctx) -> bool:
    try:
        return bool(module.match(ctx))
    except Exception:
        return False


def _safe_probe(module, ctx, force: bool, debug):
    label = getattr(module, "LABEL", module.__name__.rsplit(".", 1)[-1])
    try:
        return module.probe(ctx, force)
    except Exception as exc:
        if debug is not None:
            debug.append(f"[协议包·{label}] {ctx.vid_pid} 异常: {exc}")
        return None
