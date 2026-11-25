# -*- coding: utf-8 -*-
"""协议包：逐型号的厂商私有协议，按「设备类型 → 品牌 → 型号」三级组织。

    mouse/      鼠标    vgn.py 管 VGN 的蜻蜓 F1 / F2
    keyboard/   键盘    vgn.py 管 VGN 的 V98 Pro
    headset/    耳机
    gamepad/    手柄

一个品牌跨类型时，会在多个目录下出现同名文件（例如 mouse/vgn.py 与
keyboard/vgn.py），各管各的链路，互不干扰。每个模块头部都写清了
「适配设备 / 怎么认 / 怎么读 / 注意」，新增设备的步骤见 `packs/README.md`。

模块暴露三样东西：
    match(ctx)  -> bool         只看接口指纹，不做 I/O（除了读描述符，已缓存）
    probe(ctx, force) -> Reading | None
    ALL = True                  可选：需要把同一 VID:PID 的**所有接口**放进
                                同一个 ctx（华硕 Omni 接收器要在控制接口上
                                核对配对表，电量却在键盘接口上）
    LABEL = "华硕"               可选：调试日志里的名字

`PACKS` 的顺序 = 优先级：鼠标 → 键盘 → 耳机 → 手柄，组内顺序见各目录的
`__init__.py`。同一台设备被多条链路命中时，`scanner` 会按 score() 保留一条。
"""
from __future__ import annotations

import time

from model import Device
from providers import hidlist
from providers.hidpath import is_bluetooth, phys_token
from providers.inputidle import wait_idle
from providers.packs import base, gamepad, headset, keyboard, mouse

# 四个类型的顺序与各自组内顺序，合起来就是全局优先级。
# 不同类型之间的判据互斥（VID:PID 或接口指纹不同），所以组间顺序只影响
# "先试哪一类"，不影响正确性；会抢同一只接收器的链路都排在同一个类型里。
PACKS = mouse.MODULES + keyboard.MODULES + headset.MODULES + gamepad.MODULES

# 整个通道的预算。超了就不再开新设备：宁可这一轮少认一台，
# 也不要把一次刷新拖成十几秒。
BUDGET_S = 9.0
# 整轮扫描前的让位等待上限：用户停手 0.6 秒就继续，最多等这么久。
SCAN_IDLE_LIMIT = 0.8


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

    # 厂商帧与按键报文共用一条空中链路：打字中途插帧会把 key-up 挤到命令
    # 往返之后，用户看到的就是"按下去半天没反应"。用户正在连续输入时整轮
    # 跳过，比让每个模块各等一次更划算，也避免把 9 秒预算耗在等待上。
    # 让位不写失败缓存，下一轮刷新照常读。
    if not wait_idle(limit=SCAN_IDLE_LIMIT):
        if debug is not None:
            debug.append("[协议包] 用户正在输入，本轮跳过")
        return []

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
