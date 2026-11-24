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
from providers.inputidle import wait_idle

EVISION_VID = 0x320F
# 0x320F 是 Evision（ATK / VGN / VXE 共用）的厂商 ID。旗下型号极多：
# 键盘 VXE75/VXE99、鼠标 Dragonfly F1、R1、蜻蜓…… 换个型号就换个 PID，
# 按 PID 列白名单必然漏掉刚出的鼠标。所以只要 VID 对上就试：
# 协议不通时查询自己会超时退出，不会误报电量，代价只是首次多等一个往返。

REPORT_ID = 0x04
CMD_BATTERY = 0x1A
REPORT_LEN = 64          # 含报号

# 同一条命令有两套写法，实测两种都存在：
#   1) VGN / ATK HUB：arg=0，校验和 = ~sum(bytes[3:])
#   2) WOB 网页驱动（Rainy75 / Wave75）：arg=6，校验和 = sum(bytes[3:])
# 两种都是只读查询，先问 1)，不通再按 WOB 的节奏慢慢等。
FRAME_VARIANTS = ((0x00, True), (0x06, False))   # (arg, 校验和取反)

# WOB 那套的应答不是立刻回来的：接收器大约 5 秒一班把命令转给键盘，
# 首帧到第一个回包要 5~12 秒，按 1.2 秒的超时永远读不到。
# 长窗口只在"这台设备确认过吃 WOB 这套"或"从没读到过、且距上次长尝试超过
# SLOW_RETRY"时启用，避免每轮刷新都白等十几秒。
SLOW_WINDOW = 14.0
SLOW_RESEND = 1.5
SLOW_RETRY = 1800.0
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
# 确认走 WOB 那套慢协议的设备（key），之后每轮都用长窗口问
_SLOW_DEVICES: set[str] = set()
# 长窗口也失败过的设备：半小时内不再试长窗口
_SLOW_FAIL: dict[str, float] = {}


def _frame(arg: int, inverted: bool) -> list[int]:
    body = bytes([CMD_BATTERY, arg]) + b"\x00" * 60
    total = sum(body) & 0xFFFF
    checksum = (total ^ 0xFFFF) if inverted else total
    return ([REPORT_ID, checksum & 0xFF, (checksum >> 8) & 0xFF, CMD_BATTERY, arg]
            + [0] * 59)


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


def _parse(reply: bytes):
    """回包 → (电量, 充电, 说明)。不是电量应答就返回 None。

    状态字节必须是 0 才认，宁可这一轮读不到，也不拿别的字段当电量。
    """
    if len(reply) < 10 or reply[0] != REPORT_ID or reply[3] != CMD_BATTERY:
        return None
    code = reply[7]
    level = reply[8]
    charging = reply[9] in (1, 2)
    if code == 0xFF:
        return None, False, "休眠"
    if code == 0 and 1 <= level <= 100:
        return float(level), charging, "正常"
    if code:
        return None, False, f"状态码 0x{code:02X}"
    return None


def _query(path: bytes, slow: bool = False) -> tuple[float | None, bool, str]:
    """返回 (电量, 是否充电, 状态说明)。

    slow=False：按 VGN/ATK 那套问一次，等 1.2 秒；
    slow=True ：两套写法轮流补发，最长等 SLOW_WINDOW 秒（WOB 键盘 5~12 秒才回）。
    """
    dev = hid.device()
    try:
        dev.open_path(path)
    except Exception as exc:
        return None, False, f"打开失败: {exc}"
    try:
        dev.set_nonblocking(True)
        status = "未应答"
        deadline = time.monotonic() + (SLOW_WINDOW if slow else 1.2)
        next_send = 0.0
        variant = 0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:
                # 先丢掉上一次查询残留的应答帧。设备可能把上一拍的应答留在缓冲里，
                # 不清理就会读到"上一拍的电量"，看起来像读数总是慢一拍。
                for _ in range(16):
                    try:
                        if not dev.read(REPORT_LEN):
                            break
                    except Exception:
                        break
                arg, inverted = FRAME_VARIANTS[variant % len(FRAME_VARIANTS)]
                variant += 1
                # 打字中途插厂商帧会挤丢 key-up，让系统先空闲 0.3 秒
                wait_idle(0.3, 1.2)
                try:
                    dev.write(_frame(arg, inverted))
                except Exception as exc:
                    return None, False, f"发送失败: {exc}"
                next_send = time.monotonic() + (SLOW_RESEND if slow else 1.2)
            try:
                data = dev.read(REPORT_LEN)
            except Exception:
                data = None
            if not data:
                time.sleep(0.01)
                continue
            hit = _parse(bytes(data))
            if hit is None:
                continue
            level, charging, note = hit
            if level is not None:
                return level, charging, "正常"
            status = note
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
            # 确认过吃 WOB 慢协议的设备每轮都等；没确认过的只偶尔试一次长窗口，
            # 否则一台不支持的 320F 设备会让每轮刷新都白等十几秒。
            slow = key in _SLOW_DEVICES
            if not slow and (cached is None or cached[1] is None):
                slow = force or (now - _SLOW_FAIL.get(key, 0.0) > SLOW_RETRY)
            level, charging, status = _query(info["path"], slow=slow)
            if slow:
                if level is not None:
                    _SLOW_DEVICES.add(key)
                    _SLOW_FAIL.pop(key, None)
                else:
                    _SLOW_FAIL[key] = now
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
                f"充电={charging} 状态={status}{'（慢协议）' if key in _SLOW_DEVICES else ''}"
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
