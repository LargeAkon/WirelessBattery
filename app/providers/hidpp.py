# -*- coding: utf-8 -*-
"""通道一：HID++ 2.0 协议探测。

不依赖具体型号：对每一个罗技 HID++ 端点，逐个槽位（1-6，以及直连时的 0xFF）
发送协议握手，能应答的即为在用设备；再用标准特性号取名称与电量。
换任何罗技新设备都自动生效，无需改代码。
"""
from __future__ import annotations

import time

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, MOUSE, KEYBOARD, HEADSET, UNKNOWN
from providers import proto
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth, phys_token

LOGITECH_VID = 0x046D
REPORT_SHORT = 0x10
REPORT_LONG = 0x11

# 标准 HID++ 2.0 特性号
FEATURE_ROOT = 0x0000
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_LEVEL_STATUS = 0x1000
FEATURE_BATTERY_VOLTAGE = 0x1001
FEATURE_UNIFIED_BATTERY = 0x1004

SLOTS = (1, 2, 3, 4, 5, 6)
DIRECT_SLOT = 0xFF

# 已确认"不应答 HID++"的端点缓存：避免每次刷新都白跑一遍握手。
# 只缓存 2 分钟 —— 曾经设成 30 分钟，结果用户拔掉 USB 线让鼠标回到接收器模式后，
# 接收器仍被判"死"而看不见设备。接收器随时可能有设备上线，负缓存不能太长。
_DEAD_ENDPOINTS: dict[tuple, float] = {}
_DEAD_TTL = 120.0

# 只接受 20 字节长报文的端点（C54D 这类 LIGHTSPEED 接收器：短报文写进去了
# 却不回应答，每次先试短报文都要白等一个超时）。记住偏好，下次直接用长报文起步。
_LONG_ONLY: dict[tuple, float] = {}
_LONG_TTL = 3600.0

# 已确认存在设备的槽位：接收器插同一个 USB 口时槽位是固定的，先探已知槽位
# 能省掉 5 次空槽位超时（0.25s × 5）。缓存失效时自动退回全槽位扫描。
_SLOT_CACHE: dict[tuple, tuple[float, tuple[int, ...]]] = {}
_SLOT_TTL = 3600.0

# 上一次枚举到的 HID++ 接口集合。插拔 USB 线会让集合变化：
# GPW 插线时出现 C09B、接收器 C54D 上的设备离线；拔线则相反。
# 集合一变就清空"死端点"负缓存，否则拔线后接收器最多要等 2 分钟才被重新探测。
_LAST_IFACES: set = set()


class HidppError(Exception):
    def __init__(self, code: int):
        self.code = code
        super().__init__(f"HID++ error 0x{code:02X}")


class Endpoint:
    """一个 HID++ 端点（通常是接收器或直连外设本身）。"""

    def __init__(self, path: bytes, transport: str, prefer_long: bool = False):
        self.path = path
        self.transport = transport
        self.dev = None
        # 已知只吃长报文的端点直接长报文起步，省掉一次注定失败的短报文往返
        self.prefer_long = bool(prefer_long)
        self.long_mode: bool | None = True if prefer_long else None
        self._features: dict[int, int | None] = {}
        # 低 4 位是 software id。0 留给设备主动上报，我们从 1 轮换，
        # 这样上一问的迟到应答不会被下一问当成自己的结果。
        self._sw = 1

    # ---------- 生命周期 ----------
    def open(self) -> bool:
        if hid is None:
            return False
        try:
            self.dev = hid.device()
            self.dev.open_path(self.path)
            self.dev.set_nonblocking(0)
            return True
        except Exception:
            self.dev = None
            return False

    def close(self) -> None:
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.dev = None
        self._features.clear()
        self.long_mode = True if self.prefer_long else None
        self._sw = 1

    # ---------- 原始收发 ----------
    def _frame(self, slot: int, feature: int, function: int, params: bytes,
               long_msg: bool, sw: int):
        size = 20 if long_msg else 7
        buf = bytearray(size)
        buf[0] = REPORT_LONG if long_msg else REPORT_SHORT
        buf[1] = slot
        buf[2] = feature
        buf[3] = ((function & 0x0F) << 4) | (sw & 0x0F)
        buf[4:4 + min(len(params), size - 4)] = params[:size - 4]
        return buf

    def request(self, slot: int, feature: int, function: int, params: bytes = b"",
                timeout: float = 0.35, force_long: bool | None = None) -> bytes:
        if not self.dev:
            raise HidppError(0xFE)
        long_msg = (len(params) > 3) if force_long is None else force_long
        if self.long_mode is not None and force_long is None:
            long_msg = (len(params) > 3) or self.long_mode
        sw = self._sw
        self._sw = 1 if self._sw >= 0x0F else self._sw + 1
        self._drain()

        attempts = [long_msg]
        # 只有在"还没确定该端点吃哪种报文"时才双试。
        # 之前一旦失败就两种都试，而 C54D 这类接收器在设备离线时 7 个槽位全部超时，
        # 每个槽位付两遍超时，首轮扫描光这一项就吃掉 2 秒。long_mode 是实测出来的，
        # 已知就只走一种；不确定时才回退。
        if force_long is None and self.long_mode is None:
            attempts.append(not long_msg)  # 报文长度不被接受时切换另一种

        last_err: Exception | None = None
        for lm in attempts:
            try:
                self.dev.write(bytes(self._frame(slot, feature, function, params, lm, sw)))
            except Exception as exc:
                last_err = exc
                continue

            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                try:
                    reply = self.dev.read(64, max(1, int(left * 1000)))
                except Exception as exc:
                    last_err = exc
                    break
                if not reply:
                    break
                if len(reply) < 4 or reply[0] not in (REPORT_SHORT, REPORT_LONG):
                    continue
                if reply[1] != slot:
                    continue
                # 带回本次 software id 的才是这一问的应答。
                # 有的接收器不改这个半字节，仍回 0，那种也收下。
                # 带别的非 0 编号的是上一问迟到的包，丢掉。
                got = reply[3] & 0x0F
                if got not in (sw, 0):
                    continue
                if reply[2] == 0xFF:  # 错误应答
                    self.long_mode = lm
                    raise HidppError(reply[4] if len(reply) > 4 else 0)
                if reply[2] != feature:
                    continue
                if (reply[3] >> 4) != (function & 0x0F):
                    continue
                self.long_mode = lm
                return bytes(reply[4:])

        raise HidppError(0xFD) if last_err is None else last_err  # type: ignore[return-value]

    def _drain(self) -> None:
        if not self.dev:
            return
        try:
            self.dev.set_nonblocking(1)
            for _ in range(16):
                if not self.dev.read(64, 1):
                    break
        except Exception:
            pass
        finally:
            try:
                self.dev.set_nonblocking(0)
            except Exception:
                pass

    # ---------- 协议层 ----------
    def protocol_version(self, slot: int, timeout: float = 0.25) -> tuple[int, int] | None:
        """能收到合法应答即视为该槽位在用。

        这里曾经要求 payload[0:2] 都不是 0，结果 C54D 接收器（GPW3 的接收器）
        把协议应答成 `00 00 02 ...` 就被判成"不应答"，整条罗技链路直接失效。
        实际上 request() 只返回属于本槽位、本特性、本函数的正常应答（错误应答
        会抛 HidppError），所以"拿到非空 payload"本身就是设备存在的充分证据。

        超时 0.16s：实测应答 20ms 内返回，但**设备从省电态唤醒要 100~300ms**。
        曾经压到 0.10s 省首扫时间，结果鼠标一闲置就被判成"无设备"直接消失。
        宁可每轮多花几十毫秒，也不能让设备凭空不见。
        """
        try:
            r = self.request(slot, FEATURE_ROOT, 0x00, timeout=timeout)
        except Exception:
            return None
        return proto.parse_hidpp_version(r)

    def get_feature(self, slot: int, feature_id: int) -> int | None:
        cache_key = (slot, feature_id)
        if cache_key in self._features:
            return self._features[cache_key]
        try:
            r = self.request(slot, FEATURE_ROOT, 0x00,
                             bytes([feature_id >> 8, feature_id & 0xFF]))
            idx = r[0] if r else 0
            value = idx if 0 < idx < 0xFF else None
        except Exception:
            value = None
        self._features[cache_key] = value
        return value

    def device_name(self, slot: int) -> str:
        """取设备名。

        0x0005 有两个函数：func 0 = 名称长度，func 1（报文里是 0x10）= 名称本身。
        原来错把 func 0 当名字读，拿到的只有一个长度字节，解出来是空串或乱码，
        名称一空就落到"接收器 #槽位"，类型也就判不出来。
        """
        idx = self.get_feature(slot, FEATURE_DEVICE_NAME)
        if not idx:
            return ""
        length = 0
        try:
            r = self.request(slot, idx, 0x00, timeout=0.35)
            if r:
                length = r[0]
        except Exception:
            length = 0

        # 优先"不带参数"：C54D 这类 LIGHTSPEED 接收器对 [length] 参数回
        # ERROR 0x02（invalid argument），空参数时反而直接吐出完整名称。
        # 少数机型（如 G915 接收器）必须给长度，所以保留第二档尝试。
        attempts = [b""]
        if length:
            attempts.append(bytes([length]))
        for params in attempts:
            try:
                r = self.request(slot, idx, 0x01, params, timeout=0.5)
            except Exception:
                continue
            if not r:
                continue
            name = r.split(b"\x00", 1)[0]
            text = name.decode("utf-8", "ignore").strip()
            # 解码失败会得到控制字符，宁可返回空让上层用"接收器 #槽位"兜底
            if text and text.isprintable():
                return text
        return ""

    # ---------- 电量 ----------
    def battery(self, slot: int) -> tuple[float | None, bool, str]:
        """返回 (百分比, 是否充电, 来源特性)。

        新机型的百分比在 0x1004。先问它，避免一个不存在的旧特性
        被串包应答误判之后，把真正的电量挡掉。
        """
        # 0x1004 统一电量。函数号是 0x01（报文里的 0x10）。
        # 第 0 字节就是百分比，没有百分比时才用第 1 字节的粗档。
        idx = self.get_feature(slot, FEATURE_UNIFIED_BATTERY)
        if idx:
            try:
                p = self.request(slot, idx, 0x01, timeout=0.4)
            except Exception:
                p = b""
            parsed = proto.parse_hidpp20_unified(p)
            if parsed is not None:
                level, charging = parsed
                return level, charging, "HID++ 统一电量"

        # 0x1000：第 0 字节是百分比，第 2 字节是状态枚举，不是另一份电量。
        idx = self.get_feature(slot, FEATURE_BATTERY_LEVEL_STATUS)
        if idx:
            try:
                parsed = proto.parse_hidpp20_level(self.request(slot, idx, 0x00))
            except Exception:
                parsed = None
            if parsed is not None:
                level, charging = parsed
                return level, charging, "HID++ 电量状态"

        # 0x1001 只给电压。G502 这类机型没有百分比字节，要按电压曲线换算。
        idx = self.get_feature(slot, FEATURE_BATTERY_VOLTAGE)
        if idx:
            try:
                parsed = proto.parse_hidpp20_voltage(self.request(slot, idx, 0x00))
            except Exception:
                parsed = None
            if parsed is not None:
                level, charging = parsed
                return level, charging, "HID++ 电池电压"

        level, charging, src = self.battery_v1(slot)
        if level is not None:
            return level, charging, src
        return None, False, ""

    def _rap(self, slot: int, sub_id: int, reg: int, timeout: float) -> bytes | None:
        """HID++ 1.0 读寄存器。短报文优先，失败再试长报文。"""
        if not self.dev:
            return None
        for long_msg in (False, True):
            size = 20 if long_msg else 7
            buf = bytearray(size)
            buf[0] = REPORT_LONG if long_msg else REPORT_SHORT
            buf[1] = slot
            buf[2] = sub_id
            buf[3] = reg
            try:
                self.dev.write(bytes(buf))
            except Exception:
                continue
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                left = deadline - time.monotonic()
                try:
                    reply = self.dev.read(64, max(1, int(left * 1000)))
                except Exception:
                    break
                if not reply or len(reply) < 4:
                    continue
                if reply[0] not in (REPORT_SHORT, REPORT_LONG) or reply[1] != slot:
                    continue
                if reply[2] == 0x8F:
                    return None
                if reply[2] == sub_id and reply[3] == reg:
                    return bytes(reply[4:])
        return None

    def battery_v1(self, slot: int, timeout: float = 0.25) -> tuple[float | None, bool, str]:
        """优联上的 HID++ 1.0 设备没有 2.0 特性表，电量在寄存器里。"""
        mileage = self._rap(slot, 0x81, 0x0D, timeout)
        if mileage:
            parsed = proto.parse_hidpp10_mileage(mileage)
            if parsed:
                level, charging = parsed
                return level, charging, "HID++ 1.0 电量"
        status = self._rap(slot, 0x81, 0x07, timeout)
        if status:
            parsed = proto.parse_hidpp10_status(status)
            if parsed:
                level, charging = parsed
                return level, charging, "HID++ 1.0 电量"
        return None, False, ""


def _classify(name: str, transport: str) -> str:
    n = (name or "").lower()
    # 罗技命名陷阱：GPW3 的设备名就是 "PRO X 2"（属于鼠标 G PRO X SUPERLIGHT 系列），
    # 而耳机叫 "PRO X Wireless" / "PRO X 2 LIGHTSPEED"。原来把 "pro x" 当耳机关键词，
    # 结果鼠标被判成耳机。改成先认型号里的 superlight，再用带限定词的耳机关键词。
    if "superlight" in n:
        return MOUSE
    headset_keys = ("headset", "headphone", "earbud", "zone ", "g733", "g435", "g535",
                    "g335", "pro x wireless", "pro x 2 lightspeed", "pro x lightspeed",
                    "astrocade", "耳机", "耳麦")
    if any(k in n for k in headset_keys):
        return HEADSET
    keyboard_keys = ("keyboard", "keys", "kbd", "k380", "k400", "k650", "k780", "k850",
                     "g915", "g815", "g413", "g513", "pop keys", "craft", "键盘")
    if any(k in n for k in keyboard_keys):
        return KEYBOARD
    mouse_keys = ("mouse", "mx master", "mx anywhere", "ergo", "lift", "m720", "m590",
                  "g502", "g304", "g305", "g403", "g pro", "gpx", "superlight",
                  "pro x", "鼠标")
    if any(k in n for k in mouse_keys):
        return MOUSE
    return UNKNOWN


def scan_logitech(debug: list | None = None, force: bool = False) -> list[Device]:
    """扫描全部 HID++ 端点（不限厂商），返回在用设备。

    判定标准是"设备是否按 HID++ 协议应答"，而非品牌白名单：
    0xFF00 厂商页上能正确应答协议握手的设备都会被纳入。

    force=True（手动刷新）时无视"死端点"负缓存：用户点刷新就是明示
    "现在给我重新探一遍"，还拿缓存挡回去等于按钮没反应。
    """
    if hid is None:
        return []

    devices: list[Device] = []
    interfaces = hid_devices()

    # 短报文 (usage 0x01) 和长报文 (usage 0x02) 是同一个物理接口。
    # Bolt 接收器的协议口在 0xFF43，不在 0xFF00。长报文优先，
    # 并且把接收器实例算进键里，两只相同型号的接收器不会只探第一只。
    def _hidpp_page(info: dict) -> bool:
        if not info.get("path") or is_bluetooth(info.get("path")):
            return False
        page = info.get("usage_page") or 0
        use = info.get("usage") or 0
        if page == 0xFF00 and use in (0x0001, 0x0002):
            return True
        return page == 0xFF43 and use in (0x0001, 0x0002, 0x0202)

    candidates = [i for i in interfaces if _hidpp_page(i)]
    candidates.sort(key=lambda i: 0 if i.get("usage") in (0x0002, 0x0202) else 1)

    # 接口集合变化 = 插拔过设备（有线/无线互切）。此时之前判"死"的端点很可能
    # 已经复活，必须立刻给它一次机会，不能等 120s 的负缓存过期。
    global _LAST_IFACES
    current_ifaces = {(i.get("vendor_id") or 0, i.get("product_id") or 0,
                       i.get("interface_number"),
                       phys_token(i.get("path")).rsplit("&", 2)[0])
                      for i in candidates}
    if current_ifaces != _LAST_IFACES:
        _DEAD_ENDPOINTS.clear()
        _LAST_IFACES = current_ifaces

    seen_paths: set = set()
    seen_ifaces: set = set()
    now = time.monotonic()
    for info in candidates:
        path = info["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)

        vendor = info.get("vendor_id") or 0
        product_id = info.get("product_id") or 0
        # 去重键取到 "a&32f9a424" 这一层，不是完整的 collection 号：
        # 同一只接收器的 5 个 collection 都长在同一个 MI 接口上，
        # 用完整路径会把它们当成 5 只设备，每只各握手一轮（实测 4.0 秒），
        # 而它们其实是同一条协议通道。两只同型号接收器仍然区分得开。
        phys = phys_token(path).rsplit("&", 2)[0]
        iface_key = (vendor, product_id, info.get("interface_number"), phys)
        if iface_key in seen_ifaces:
            continue
        seen_ifaces.add(iface_key)
        if now < _DEAD_ENDPOINTS.get(iface_key, 0.0) and not force:
            continue

        product = info.get("product_string") or ""
        # usage 0x0002 这个 collection 本身就是"长报文口"，直接长报文起步。
        # 若还按"先短后长"试，短报文写进去不会回，白等一个超时，而且接收器
        # 在短报文失败后要一点恢复时间，反而连后面的长报文也赶不上。
        prefer_long = (info.get("usage") in (0x0002, 0x0202)
                       or now < _LONG_ONLY.get(iface_key, 0.0))
        ep = Endpoint(path, product, prefer_long)
        if not ep.open():
            continue
        try:
            slots_with_device: list[tuple[int, tuple[int, int]]] = []

            cached = _SLOT_CACHE.get(iface_key)
            cached_slots = tuple(cached[1]) if cached and now < cached[0] else ()

            if cached_slots:
                # 已知这台端点的设备在哪几个槽位（接收器几乎总是 1 个）。
                # 直接探已知槽位，不要先去扫 0xFF 和 6 个空槽位 —— 那要 1 秒多，
                # 而且每一步都会打断接收器与设备之间的休眠/唤醒节奏。
                for slot in cached_slots:
                    v = ep.protocol_version(slot)
                    if v:
                        slots_with_device.append((slot, v))
                if not slots_with_device:
                    # 全部失败通常只是设备进了省电态（罗技闲置十几分钟就睡）。
                    # 给一次更长的唤醒窗口，比直接判"设备没了"合理得多。
                    for slot in cached_slots:
                        v = ep.protocol_version(slot, timeout=0.5)
                        if v:
                            slots_with_device.append((slot, v))
                if not slots_with_device:
                    # 仍然没有 → 槽位真的变了（换了 USB 口，或有线/无线互切），
                    # 退回全槽位扫描，但不再对每个空槽位长等。
                    for slot in SLOTS:
                        if slot in cached_slots:
                            continue
                        v = ep.protocol_version(slot)
                        if v:
                            slots_with_device.append((slot, v))
            else:
                # 首次见到这个端点：先探 0xFF（USB 线直连的设备对任何槽位都应答，
                # 按槽位扫会拿到 6 条同名记录），没有才是接收器，继续扫槽位。
                ver = ep.protocol_version(DIRECT_SLOT)
                if ver:
                    slots_with_device.append((DIRECT_SLOT, ver))
                else:
                    for slot in SLOTS:
                        ver = ep.protocol_version(slot)
                        if ver:
                            slots_with_device.append((slot, ver))

            v1_ready: dict[int, tuple[float, bool, str]] = {}
            if not slots_with_device and vendor == LOGITECH_VID:
                # 醒得慢，或者根本是 HID++ 1.0（优联旧鼠旧键盘不答 2.0 握手）。
                for slot in (DIRECT_SLOT, 1, 2, 3):
                    ver = ep.protocol_version(slot, timeout=0.5)
                    if ver:
                        slots_with_device.append((slot, ver))
                if not slots_with_device:
                    for slot in (DIRECT_SLOT, 1, 2, 3):
                        level, charging, src = ep.battery_v1(slot, timeout=0.28)
                        if level is None:
                            continue
                        v1_ready[slot] = (level, charging, src)
                        slots_with_device.append((slot, (1, 0)))

            if not slots_with_device:
                _DEAD_ENDPOINTS[iface_key] = time.monotonic() + _DEAD_TTL
                if debug is not None:
                    debug.append(f"[HID++] {vendor:04X}:{product_id:04X} "
                                 f"{product!r} 不应答协议握手（可能为其他私有协议）")
            else:
                _DEAD_ENDPOINTS.pop(iface_key, None)
                _SLOT_CACHE[iface_key] = (
                    time.monotonic() + _SLOT_TTL,
                    tuple(sorted(s for s, _ in slots_with_device)))
                # 这次是靠长报文才通的，记下偏好，下轮直接长报文起步
                if ep.long_mode is True and not prefer_long:
                    _LONG_ONLY[iface_key] = time.monotonic() + _LONG_TTL

            for slot, ver in slots_with_device:
                if slot in v1_ready:
                    level, charging, src = v1_ready[slot]
                    name = product or f"罗技设备 #{slot}"
                elif ver[0] == 1:
                    level, charging, src = ep.battery_v1(slot)
                    name = product or f"罗技设备 #{slot}"
                else:
                    name = ep.device_name(slot) or f"{product} #{slot}"
                    level, charging, src = ep.battery(slot)
                if debug is not None:
                    debug.append(
                        f"[HID++] {product or f'{vendor:04X}'} 槽位{slot} 协议{ver[0]}.{ver[1]} "
                        f"名称={name!r} 电量={level} 充电={charging} 来源={src or '无'}")
                if level is None:
                    continue
                kind = _classify(name, product)
                # 直连就是插着线在充电：说成"USB 有线"比"USB 直连"更好懂，
                # 而且能直接解释"为什么这台突然显示成有线了"。
                transport = ("USB 有线充电" if charging else "USB 有线"
                             ) if slot == DIRECT_SLOT else "2.4G 接收器"
                devices.append(Device(
                    key=f"hidpp:{vendor:04x}:{product_id:04x}:{slot}:{phys}",
                    name=name,
                    kind=kind,
                    level=level,
                    charging=charging,
                    source=src or "HID++",
                    transport=transport,
                    raw={"phys": phys},
                    vid_pid=f"{vendor:04X}:{product_id:04X}",
                ))
        finally:
            ep.close()

    return devices
