# -*- coding: utf-8 -*-
"""通道：Evision / VGN / VXE / ATK 2.4G 键盘（含接收器 320F:5088）。

协议来自公开逆向结论（ATK HUB / VGN HUB 行为，社区工具实测）：
  查询帧  04 <cs_lo> <cs_hi> 1A  + 59 字节 0   （cs = ~sum(bytes[3:]) & 0xFFFF）
  应答帧  04 <cs_lo> <cs_hi> 1A ... r[7] r[8] r[9]
          r[7] 状态：0=有效，0xFF=休眠/离线
          r[8] 电量 1..100
          r[9] 充电 0/1
只发送只读查询，不写入任何设置。

**为什么一轮最多只发两帧**
320F:5088 这类接收器把所有功能挂在同一个 USB 接口（MI_01）的不同 collection
上：键盘 0001:0006、鼠标 0001:0002、消费键 000C:0001、厂商 FF1C:0092、
FFEF:0000 —— 全是同一条中断通道。向厂商 collection 写一帧，接收器要先把
命令转给键盘、等键盘回话，这段时间键击上报只能排在后面。

早期实现在 14 秒窗口里每 1.5 秒补发一帧、两套写法交替，共约 9 帧，而且
首次扫描无条件走这条慢路径。表现就是：开机扫描那十几秒里，打字按下去
要等一会儿才出字。现在改成两条硬约束 ——

1. 一轮最多 2 帧；已经确认过吃哪套写法的，后续只发那一套，不再发无效帧。
2. 每帧发出前必须等到用户停手（0.6 秒无输入）；等不到就整轮放弃，
   不记失败、不动缓存，下一轮再试。

慢协议（WOB 键盘 Rainy75 / Wave75，回包要 5~12 秒）只在快路径连续失败
5 分钟后才启用，避免普通键盘为它买单。
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
# 两种都是只读查询。第二轮只在前一套没应答时才发，且最多各发一次。
FRAME_VARIANTS = ((0x00, True), (0x06, False))   # (arg, 校验和取反)

# 一轮最多发几帧。第 1 帧 = VGN 标准写法，第 2 帧 = WOB 写法。
MAX_FRAMES = 2
# 每帧窗口：普通设备实测应答 <10ms，1.2 秒足够；确认吃慢协议的才拉长。
FAST_TIMEOUT = 1.2
SLOW_TIMEOUT = 5.0
# 两帧之间的间隔。这段时间不发帧，用户可以照常打字。
FAST_GAP = 0.8
SLOW_GAP = 2.0
# 每帧发出前最多为"用户停手"等这么久。等不到就整轮放弃 ——
# 连续打字时没必要一直等，下轮刷新再来就是了。
QUERY_IDLE_LIMIT = 1.5

# 读到过电量的设备多久允许再问一次。必须严格小于充电时的 30 秒刷新间隔，
# 否则充电中的定时刷新会全部落到冷却分支，读数又开始滞后。
COOLDOWN = 20
# 状态 0xFF：协议是对的，只是设备睡了。1 分钟后可以再问。
SLEEP_COOLDOWN = 60
# 完全没应答：这台设备不吃这套协议，30 分钟内不再打扰。
FAIL_COOLDOWN = 1800
# 快路径连续失败多久之后才允许试慢协议（WOB 键盘用）。
SLOW_RETRY = 300.0
# 已确认的慢协议设备连续几次读不到就降级回快路径（设备可能已经换掉了）
SLOW_MISS_LIMIT = 3

_cache: dict[str, tuple[float, float | None, bool, str]] = {}
# 确认过吃哪套写法：0 = VGN 标准，1 = WOB
_VARIANT: dict[str, int] = {}
# 确认走 WOB 那套慢协议的设备（key）
_SLOW_DEVICES: set[str] = set()
# 快路径 / 慢路径失败的时间点，用于退避
_SLOW_FAIL: dict[str, float] = {}
# 已确认慢协议设备的连续失手次数
_SLOW_MISS: dict[str, int] = {}


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


def _order(key: str, slow: bool) -> list[int]:
    """这一轮按顺序试哪几套写法，长度不超过 MAX_FRAMES。

    已经知道设备吃哪一套时就固定用它 —— 交替发无效帧只会白占通道。
    慢协议靠"同一帧补发"对抗丢包，不再换另一套。
    """
    known = _VARIANT.get(key)
    if known is not None:
        return [known, known] if slow else [known]
    return [0, 1]


def _await_reply(dev, window: float):
    """在窗口内等一帧电量应答。返回 ((电量, 充电) | None, 状态说明)。"""
    deadline = time.monotonic() + window
    note = ""
    while time.monotonic() < deadline:
        try:
            data = dev.read(REPORT_LEN)
        except Exception:
            return None, note
        if not data:
            time.sleep(0.01)
            continue
        hit = _parse(bytes(data))
        if hit is None:
            continue
        level, charging, text = hit
        if level is not None:
            return (level, charging), note
        note = text          # 休眠 / 状态码，留作说明
    return None, note


def _query(path: bytes, key: str, slow: bool = False):
    """返回 (电量, 是否充电, 状态说明)。

    任何一帧发出前都要等到用户停手。等不到就返回"用户输入中"，
    由调用方放弃本轮 —— 不给缓存写失败，下轮刷新再试。
    """
    dev = hid.device()
    try:
        dev.open_path(path)
    except Exception as exc:
        return None, False, f"打开失败: {exc}"
    try:
        dev.set_nonblocking(True)
        # 丢掉上一拍残留的应答，否则会读到"上一拍的电量"。
        for _ in range(16):
            try:
                if not dev.read(REPORT_LEN):
                    break
            except Exception:
                break

        order = _order(key, slow)[:MAX_FRAMES]
        window = SLOW_TIMEOUT if slow else FAST_TIMEOUT
        gap = SLOW_GAP if slow else FAST_GAP
        status = "未应答"
        for index, variant in enumerate(order):
            if index and gap > 0:
                # 间隔期不发帧，用户可以照常打字
                time.sleep(gap)
            if not wait_idle(limit=QUERY_IDLE_LIMIT):
                return None, False, "用户输入中"
            arg, inverted = FRAME_VARIANTS[variant]
            try:
                dev.write(_frame(arg, inverted))
            except Exception as exc:
                return None, False, f"发送失败: {exc}"
            hit, note = _await_reply(dev, window)
            if hit is not None:
                _VARIANT[key] = variant
                return hit[0], hit[1], "正常"
            if note:
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
    # 同一只接收器会在多个 collection 上暴露 FF1C:0092 / FFEF:0000（同一接口的
    # 不同 collection 各算一条）。它们共用一条中断通道，问第一条就够了：
    # 失败时问第二条也只是再占用一次通道，纯属给自己加延迟。
    # 去重键取到 (phys_root, interface_number) 这一层，不同接口仍然分别试。
    done: set[tuple] = set()

    for info in _endpoints():
        vid, pid = info["_vid_pid"]
        phys = info.get("_phys") or ""
        phys_root = phys.rsplit("&", 2)[0]
        iface = info.get("interface_number")
        group_key = (vid, pid, phys_root, iface)
        if group_key in done:
            continue
        done.add(group_key)

        key = f"evision:{vid:04x}:{pid:04x}:{iface}:{phys}"
        name = _clean_name(info.get("product_string") or "",
                           info.get("manufacturer_string") or "")
        cached = _cache.get(key)
        # 读到过电量的按 20s 冷却；协议对但设备睡了按 1 分钟；
        # 完全不应答的按 30 分钟 —— 每轮都去等一台不支持的设备毫无意义。
        if cached and cached[1] is not None:
            cool = COOLDOWN
        elif cached and cached[3] == "休眠":
            cool = SLEEP_COOLDOWN
        else:
            cool = FAIL_COOLDOWN

        if not force and cached and now - cached[0] < cool:
            level, charging, status = cached[1], cached[2], cached[3]
            if debug is not None:
                debug.append(f"[Evision] {name} 使用 {int(now - cached[0])}s 前读数")
        else:
            # 慢协议只给三类设备：已经确认吃这一套的、快路径连续失败 5 分钟的、
            # 以及用户手动刷新点名的。启动扫描一律走快路径 —— 普通键盘第 1 帧
            # 就应答，没必要替 WOB 键盘陪跑十几秒。
            slow = key in _SLOW_DEVICES
            if not slow:
                failed_at = _SLOW_FAIL.get(key)
                slow = force or (failed_at is not None and now - failed_at > SLOW_RETRY)

            level, charging, status = _query(info["path"], key, slow=slow)

            if status == "用户输入中":
                # 让位：不发帧、不写缓存，保留上一次读数，下轮再来。
                if debug is not None:
                    debug.append(f"[Evision] {name} 用户正在输入，本轮跳过")
                cached = _cache.get(key)
                if cached and cached[1] is not None:
                    level, charging = cached[1], cached[2]
                else:
                    continue
            elif level is not None:
                _cache[key] = (now, level, charging, status)
                if slow:
                    _SLOW_DEVICES.add(key)
                    _SLOW_FAIL.pop(key, None)
                    _SLOW_MISS.pop(key, None)
                else:
                    _SLOW_FAIL.pop(key, None)
            else:
                if slow:
                    # 确认过的慢协议设备读不到：连续失手够多就降级回快路径
                    miss = _SLOW_MISS.get(key, 0) + 1
                    _SLOW_MISS[key] = miss
                    if miss >= SLOW_MISS_LIMIT:
                        _SLOW_DEVICES.discard(key)
                        _SLOW_MISS.pop(key, None)
                        _SLOW_FAIL[key] = now
                else:
                    # 快路径没应答：记下时间，5 分钟后才允许试慢协议
                    _SLOW_FAIL[key] = now
                if cached:
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

        # 查询超时说明这条口不说 Evision。休眠是设备应答过，仍然留下。
        if level is None and status != "休眠":
            continue
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
