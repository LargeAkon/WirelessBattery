# -*- coding: utf-8 -*-
"""通道：Evision / VGN / VXE / ATK 2.4G 键盘（含接收器 320F:5088）。

协议来自公开逆向结论（ATK HUB / VGN HUB 行为，社区工具实测）：
  查询帧  04 <cs_lo> <cs_hi> 1A  + 59 字节 0   （cs = ~sum(bytes[3:]) & 0xFFFF）
  应答帧  04 <cs_lo> <cs_hi> 1A ... r[7] r[8] r[9]
          r[7] 状态：0=有效，0xFF=休眠/离线
          r[8] 电量 1..100
          r[9] 充电 0/1
只发送这一条只读查询，不写入任何设置。为省电，自动刷新时同一设备 10 分钟内只问一次。
"""
from __future__ import annotations

import time

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, KEYBOARD, MOUSE, HEADSET
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth, phys_token

EVISION_VID = 0x320F
# 0x320F 是 Evision（ATK / VGN / VXE 共用）的厂商 ID。旗下型号极多：
# 键盘 VXE75/VXE99、鼠标 Dragonfly F1、R1、蜻蜓…… 换个型号就换个 PID，
# 按 PID 列白名单必然漏掉刚出的鼠标。所以只要 VID 对上就试：
# 协议不通时查询自己会超时退出，不会误报电量，代价只是首次多等一个往返。

REPORT_ID = 0x04
CMD_BATTERY = 0x1A
REPORT_LEN = 64          # 含报号
# 同一设备的最小重复查询间隔（秒）。
# 原来这里是 600s，正好等于最小刷新间隔（10 分钟）：定时器有几秒误差时，
# now-cached 会落在 <600 里被判成"仍在冷却"，于是每两次刷新才真正读一次，
# 电量最长滞后 20 分钟 —— 用户看到的"驱动 70、这里 60"就是这么来的（充电时涨得快）。
# 这条命令只读、一次 HID 往返毫秒级，20s 足够挡掉同一瞬间的重叠查询。
# 硬约束：必须严格小于 main.py 的 CHARGE_REFRESH_MS（充电时 30s 一刷）。
# 两者相等或更大时，充电中的定时刷新会全部落到"仍在冷却"分支，读数又开始滞后。
COOLDOWN = 20
# 查不到时的冷却时间要长得多：说明这台设备根本不吃这套协议，
# 每轮都去等它超时只会把刷新拖慢好几秒。3 分钟内不再打扰它，
# 手动刷新（force=True）可以立刻重试。
FAIL_COOLDOWN = 180

_cache: dict[str, tuple[float, float | None, bool, str]] = {}


def _frame() -> list[int]:
    body = bytes([CMD_BATTERY]) + b"\x00" * 61
    checksum = (sum(body) & 0xFFFF) ^ 0xFFFF
    return [REPORT_ID, checksum & 0xFF, (checksum >> 8) & 0xFF, CMD_BATTERY] + [0] * 59


def _clean_name(product: str, manufacturer: str) -> str:
    name = (product or "").strip()
    for suffix in (" 2.4G Dongle", " 2.4G Receiver", " Wireless Receiver",
                   " Dongle", " Receiver", " 2.4G", " USB Receiver"):
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)].strip()
    if not name:
        name = (manufacturer or "无线键盘").strip()
    return name


def _classify(name: str, has_keyboard: bool, has_mouse: bool) -> str:
    low = name.lower()
    if any(k in low for k in ("mouse", "鼠标", "dragonfly", "蜻蜓", "f1 ", "r1 ")):
        return MOUSE
    if any(k in low for k in ("keyboard", "键盘", "vxe", "vgn", "atk", "s99", "n75")):
        return KEYBOARD
    if any(k in low for k in ("headset", "耳机")):
        return HEADSET
    if has_keyboard and not has_mouse:
        return KEYBOARD
    if has_mouse and not has_keyboard:
        return MOUSE
    return KEYBOARD


def _endpoints() -> list[dict]:
    """返回该读电量的厂商端点。

    320F 是 Evision 自己的厂商号。别的品牌只要暴露 FF1C:0092，
    用的就是同一条查询，不再要求厂商号必须是 320F。
    """
    if hid is None:
        return []
    groups: dict[tuple, list[dict]] = {}
    interfaces = hid_devices()
    for info in interfaces:
        path = info.get("path")
        if not path or is_bluetooth(path):
            continue
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not vid:
            continue
        groups.setdefault((vid, pid, phys_token(path)), []).append(info)

    out: list[dict] = []
    for key, infos in groups.items():
        vid = key[0]
        usages = {(i.get("usage_page") or 0, i.get("usage") or 0) for i in infos}
        has_keyboard = any(p == 0x0001 and u == 0x0006 for p, u in usages)
        has_mouse = any(p == 0x0001 and u == 0x0002 for p, u in usages)
        ff = [i for i in infos
              if i.get("usage_page") == 0xFF1C and i.get("usage") == 0x0092]
        if ff:
            targets = ff
        elif vid == EVISION_VID:
            targets = [i for i in infos if (i.get("usage_page") or 0) >= 0xFF00][:1]
        else:
            continue
        for info in targets:
            item = dict(info)
            item["_has_keyboard"] = has_keyboard
            item["_has_mouse"] = has_mouse
            item["_vid_pid"] = (vid, key[1])
            item["_phys"] = key[2]
            item["_attempts"] = 3 if vid == EVISION_VID else 1
            out.append(item)
    return out


def _query(path: bytes, attempts: int = 3) -> tuple[float | None, bool, str]:
    """返回 (电量, 是否充电, 状态说明)。"""
    dev = hid.device()
    try:
        dev.open_path(path)
    except Exception as exc:
        return None, False, f"打开失败: {exc}"
    try:
        dev.set_nonblocking(True)
        status = "未应答"
        for attempt in range(attempts):
            # 先丢掉上一次查询残留的应答帧。设备可能把上一拍的应答留在缓冲里，
            # 不清理就会读到"上一拍的电量"，看起来像读数总是慢一拍。
            for _ in range(16):
                if not dev.read(REPORT_LEN):
                    break
            try:
                dev.write(_frame())
            except Exception as exc:
                return None, False, f"发送失败: {exc}"
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                try:
                    data = dev.read(REPORT_LEN)
                except Exception:
                    data = None
                if not data:
                    time.sleep(0.01)
                    continue
                reply = bytes(data)
                if len(reply) < 10 or reply[0] != REPORT_ID or reply[3] != CMD_BATTERY:
                    continue
                code = reply[7]
                level = reply[8]
                charging = reply[9] in (1, 2)
                if code == 0 and 0 <= level <= 100:
                    return float(level), charging, "正常"
                if code == 0xFF:
                    status = "休眠"
                elif code != 0:
                    status = f"状态码 0x{code:02X}"
            if attempt < attempts - 1:
                time.sleep(0.25)
        return None, False, status
    finally:
        try:
            dev.close()
        except Exception:
            pass


def scan_evision(debug: list | None = None, force: bool = False) -> list[Device]:
    devices: list[Device] = []
    now = time.monotonic()
    # 同一只接收器会在多个 collection 上暴露 FF1C:0092（同一 MI 接口的 Col04、
    # Col05 各算一条），逐个问一遍毫无意义：第一条读到就说明这只接收器通了，
    # 剩下的只会白白各等 1.2 秒 × 3 次 —— 实测 VGN 的 dongle 有两条，
    # 第二条永远"未应答"，整轮刷新被拖到 4.2 秒。
    # 去重键取到 "a&32f9a424" 这一层：两只同型号接收器仍能区分开。
    done_phys: set[tuple] = set()
    for info in _endpoints():
        vid, pid = info["_vid_pid"]
        phys = info.get("_phys") or ""
        phys_root = phys.rsplit("&", 2)[0]
        if (vid, pid, phys_root) in done_phys:
            continue
        iface = info.get("interface_number")
        key = f"evision:{vid:04x}:{pid:04x}:{iface}:{phys}"
        name = _clean_name(info.get("product_string") or "",
                           info.get("manufacturer_string") or "")
        cached = _cache.get(key)
        # 读到过电量的按 20s 冷却；从来没读到过的按 3 分钟冷却
        cool = COOLDOWN if (cached and cached[1] is not None) else FAIL_COOLDOWN
        if not force and cached and now - cached[0] < cool:
            level, charging, status = cached[1], cached[2], cached[3]
            if debug is not None:
                debug.append(f"[Evision] {name} 使用 {int(now - cached[0])}s 前读数")
        else:
            level, charging, status = _query(info["path"], attempts=info.get("_attempts") or 1)
            if level is not None:
                _cache[key] = (now, level, charging, status)
            elif cached:
                # 读失败（休眠）沿用上次有效值，同时标注状态
                level, charging = cached[1], cached[2]
                _cache[key] = (cached[0], cached[1], cached[2], status)
            else:
                _cache[key] = (now, None, False, status)

        if debug is not None:
            debug.append(
                f"[Evision] {vid:04X}:{pid:04X} {name!r} 电量={level} "
                f"充电={charging} 状态={status}"
            )

        # 查询超时说明这条口不说 Evision。休眠是设备应过答，仍然留下。
        if level is None and status != "休眠":
            continue
        if level is not None:
            done_phys.add((vid, pid, phys_root))
        devices.append(Device(
            key=key,
            name=name,
            kind=_classify(name, info["_has_keyboard"], info["_has_mouse"]),
            level=level,
            charging=charging,
            source="Evision 2.4G",
            transport="2.4G 接收器",
            raw={"state": status, "phys": phys, "vid_pid": f"{vid:04X}:{pid:04X}"},
            vid_pid=f"{vid:04X}:{pid:04X}",
        ))
    return devices
