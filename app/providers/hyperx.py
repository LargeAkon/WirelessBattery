# -*- coding: utf-8 -*-
"""HyperX 2.4G 耳机。

同一品牌有好几套接收器。这里只按产品号发送对应的只读电量查询，
不写静音、侧音或关机时间。应答对不上就不当成电量。
"""
from __future__ import annotations

import time

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, HEADSET
from providers import proto
from providers.hidctl import set_output_report
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth, phys_token

_FAIL: dict[tuple, float] = {}
_FAIL_FOR = 90.0

# 03F0 是 HP 收购后的接收器。0951 是金士顿时期的 Cloud II。
# 0FCC 是 Cloud III Wireless 的另一种接收器（和 05B7 同协议，只是货号不同）。
# 少了这一条，用 0FCC 那批接收器的飓风 3 就永远读不到 —— 用户看到的是
# "耳机插着、灯也亮，软件里没有这台设备"。
_HP = {
    0x05B7: "iii",
    0x0C9D: "iii",
    0x0FCC: "iii",
    0x069F: "iii",
    0x0995: "iii",
    0x0795: "iii",
    0x06BE: "iiis",
    0x02CC: "iiis",
    0x1743: "alpha",
    0x1765: "alpha",
    0x098D: "alpha",
    0x08BE: "alpha2",
    0x0E90: "flight",
    0x1749: "flight",
    0x16C4: "flight",
    0x1723: "flight",
    0x018B: "ii",
    0x0D93: "ii",
    0x0696: "ii",
    0x1718: "ii",
}
_KINGSTON = {
    0x1718: "kingston",
    0x0B92: "kingston",
    0x16EA: "kingston",
    0x16EB: "kingston",
}

_KINGSTON_BATTERY = bytes((
    0x06, 0x00, 0x02, 0x00, 0x9A, 0x00, 0x00, 0x68,
    0x4A, 0x8E, 0x0A, 0x00, 0x00, 0x00, 0xBB, 0x02,
)) + bytes(46)
_KINGSTON_CHARGE = bytes((
    0x06, 0x00, 0x02, 0x00, 0x9A, 0x00, 0x00, 0x68,
    0x4A, 0x8E, 0x0A, 0x00, 0x00, 0x00, 0xBB, 0x03,
)) + bytes(46)


def _family(vid: int, pid: int) -> str | None:
    if vid == 0x03F0:
        return _HP.get(pid)
    if vid == 0x0951:
        return _KINGSTON.get(pid)
    return None


def _cooled(key: tuple, force: bool) -> bool:
    if force:
        return False
    return time.monotonic() < _FAIL.get(key, 0.0)


def _mark_fail(key: tuple) -> None:
    _FAIL[key] = time.monotonic() + _FAIL_FOR


def _open(path):
    dev = hid.device()
    dev.open_path(path)
    # 用阻塞读 + 超时，而不是 nonblocking：nonblocking 下 hidapi 会忽略
    # 超时参数立刻返回，下面的等待循环就变成 0.45 秒的忙等（CPU 白跑满）。
    dev.set_nonblocking(False)
    return dev


def _close(dev) -> None:
    try:
        if dev is not None:
            dev.close()
    except Exception:
        pass


def _drain(dev) -> None:
    for _ in range(12):
        try:
            if not dev.read(128, 1):
                return
        except Exception:
            return


def _read_parsed(dev, seconds: float, parse):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        left = deadline - time.monotonic()
        try:
            raw = dev.read(128, max(1, int(left * 1000)))
        except Exception:
            return None
        if not raw:
            continue
        hit = parse(bytes(raw))
        if hit is not None:
            return hit
    return None


def _frames(payload: bytes, path=None) -> list[bytes]:
    """这一帧按哪几种长度发。

    优先照描述符里 0x66 那条报文的实际长度补齐 —— 有的接收器声明 64，
    有的声明 65（报告号 + 64 字节数据），发错一个字节，Windows 直接把
    整帧判成非法长度丢掉，设备一声不响。描述符读不到时两种都试。
    """
    lengths: list[int] = []
    if path is not None:
        try:
            from providers import hidreports

            outs = hidreports.reports(path).get("out", {})
            want = outs.get(payload[0]) if payload else None
            # 只信"和协议帧长度接近"的值：描述符解析一旦出偏（例如把
            # feature 报文的长度算到 out 上），照它截帧会发出一条残帧。
            if want and abs(int(want) - len(payload)) <= 8:
                lengths.append(int(want))
        except Exception:
            pass
    lengths.extend((len(payload), len(payload) + 1))
    out: list[bytes] = []
    for size in lengths:
        if size < 1 or size > 128 or size in {len(frame) for frame in out}:
            continue
        out.append(payload[:size] if len(payload) >= size
                   else payload + bytes(size - len(payload)))
    return out[:2]


def _read_once(dev, frame, parse, seconds: float):
    try:
        if not dev.write(frame):
            return None, False
    except Exception:
        return None, False
    return _read_parsed(dev, seconds, parse), True


def _query(dev, payload: bytes, parse, seconds: float = 0.4, control_path=None):
    """发一帧读电量。返回第一个能解析的应答。

    三种出口的顺序是有讲究的：
      1. 中断 OUT（hidapi write）：绝大多数接收器走这里；
      2. FEATURE：少数接收器把同一条命令挂在 feature 报文上；
      3. SET_REPORT 控制传输：HP / HyperX 这代接收器没有可用的中断 OUT
         端点，只认这一条（Linux 的 hid-hyperx-headset 也是这么发的）。
    长度只在"写失败"时才换：写成功却没应答，说明长度是对的，问题在
    协议或集合，换长度重发只是白等一个超时。
    """
    _drain(dev)
    frames = _frames(payload, control_path)
    for frame in frames:
        hit, wrote = _read_once(dev, frame, parse, seconds)
        if hit is not None:
            return hit
        if wrote:
            break                      # 长度没问题，别再换长度
    frame = frames[0]
    try:
        if dev.send_feature_report(frame) >= 0:
            hit = _read_parsed(dev, seconds, parse)
            if hit is not None:
                return hit
    except Exception:
        pass
    if control_path is not None:
        # 必须送完整帧：以前的实现裁到 62 字节，长度不足，系统直接返回
        # 失败 —— 于是"只认控制传输"的接收器永远读不到。
        if set_output_report(control_path, frame):
            return _read_parsed(dev, seconds, parse)
    return None


def _requests(family: str) -> tuple[list[bytes], list[bytes], object, object]:
    """返回 (电量帧候选, 充电帧候选, 电量解析, 充电解析)。"""
    if family == "iii":
        battery = bytes([0x66, 0x89]) + bytes(62)
        charge = bytes([0x66, 0x8A]) + bytes(62)
        # 只留一条 64 字节的帧：实际长度由 _frames 按描述符补齐（62/64/65），
        # 不必再盲试那条 62 字节的短帧 —— 每多一条 payload 就多等一个超时。
        return [battery], [charge], proto.parse_hyperx_66_battery, proto.parse_hyperx_66_charging
    if family == "iiis":
        battery = bytearray(64)
        battery[0:6] = bytes((0x0C, 0x02, 0x03, 0x01, 0x00, 0x06))
        charge = bytearray(64)
        charge[0:6] = bytes((0x0C, 0x02, 0x03, 0x01, 0x00, 0x48))
        return [bytes(battery)], [bytes(charge)], proto.parse_hyperx_iiis_battery, proto.parse_hyperx_iiis_charging
    if family == "alpha":
        battery = bytes([0x21, 0xBB, 0x0B]) + bytes(61)
        charge = bytes([0x21, 0xBB, 0x0C]) + bytes(61)
        return [battery], [charge], proto.parse_hyperx_alpha_battery, proto.parse_hyperx_alpha_charging
    if family == "alpha2":
        packet = bytes([0x50, 0x02, 0x00, 0x00]) + bytes(60)
        return [packet], [], proto.parse_hyperx_alpha2, None
    if family == "flight":
        packet = bytes([0x21, 0xFF, 0x05]) + bytes(61)
        return [packet], [], proto.parse_hyperx_flight, None
    if family == "ii":
        battery = bytes([0x06, 0xFF, 0xBB, 0x02]) + bytes(48)
        charge = bytes([0x06, 0xFF, 0xBB, 0x03]) + bytes(48)
        short_b = battery[:20]
        short_c = charge[:20]
        return [battery, short_b], [charge, short_c], proto.parse_hyperx_ii_dts_battery, proto.parse_hyperx_ii_dts_charging
    battery = _KINGSTON_BATTERY
    charge = _KINGSTON_CHARGE
    return [battery], [charge], proto.parse_hyperx_kingston_battery, proto.parse_hyperx_kingston_charging


def _ask(dev, payloads: list[bytes], parse, control_path=None):
    for payload in payloads:
        hit = _query(dev, payload, parse, control_path=control_path)
        if hit is not None:
            return hit
    return None


def _read_one(dev, family: str, control_path=None) -> tuple[float | None, bool] | None:
    battery_frames, charge_frames, parse_level, parse_charge = _requests(family)
    if family in ("alpha2", "flight"):
        return _ask(dev, battery_frames, parse_level, control_path)
    level = _ask(dev, battery_frames, parse_level, control_path)
    if level is None:
        return None
    charging = False
    if parse_charge is not None and charge_frames:
        flag = _ask(dev, charge_frames, parse_charge, control_path)
        if flag is not None:
            charging = bool(flag)
    return float(level), charging


def _prefer(info: dict, family: str) -> int:
    page = info.get("usage_page") or 0
    use = info.get("usage") or 0
    if family in ("iii", "alpha2") and page == 0xFF13:
        return 0
    if family == "ii" and page == 0xFF90:
        return 0
    if page >= 0xFF00:
        return 1
    return 5


def scan_hyperx(debug: list | None = None, force: bool = False) -> list[Device]:
    if hid is None:
        return []
    infos = hid_devices()

    groups: dict[tuple, list[dict]] = {}
    for info in infos:
        path = info.get("path")
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not path or is_bluetooth(path) or _family(vid, pid) is None:
            continue
        groups.setdefault((vid, pid, phys_token(path)), []).append(info)

    devices: list[Device] = []
    for (vid, pid, phys), members in groups.items():
        family = _family(vid, pid)
        key = ("hyperx", family, phys)
        if _cooled(key, force):
            continue
        members = sorted(members, key=lambda info: _prefer(info, family or ""))
        found = None
        tried: list[str] = []       # 只记真正打开过的接口，别把"跳过"的算成"试过"
        for info in members:
            if (info.get("usage_page") or 0) < 0xFF00 and _prefer(info, family or "") > 1:
                continue
            tried.append(f"{(info.get('usage_page') or 0):04X}:{(info.get('usage') or 0):04X}")
            dev = None
            try:
                dev = _open(info["path"])
                found = _read_one(dev, family or "", info["path"])
            except Exception:
                found = None
            finally:
                _close(dev)
            if found is not None:
                break
        if found is None:
            if not tried:
                # 这一组接口全是键鼠 / 耳机的标准集合，本来就不是电量口，
                # 一个都没打开过。既不该记失败，也不该在调试里喊"没读到"。
                continue
            _mark_fail(key)
            if debug is not None:
                debug.append(
                    f"[HyperX] {vid:04X}:{pid:04X} 方案={family} 没有读到电量 "
                    f"（已试接口 {' / '.join(tried) or '无'}）")
            continue
        level, charging = found
        if level is None and not charging:
            _mark_fail(key)
            continue
        name = ""
        for info in members:
            product = (info.get("product_string") or "").strip()
            if product:
                name = product
                break
        if not name:
            name = "HyperX 耳机"
        if debug is not None:
            debug.append(
                f"[HyperX] {vid:04X}:{pid:04X} {name!r} 方案={family} "
                f"电量={level} 充电={charging}"
            )
        devices.append(Device(
            key=f"hyperx:{vid:04x}:{pid:04x}:{phys}",
            name=name,
            kind=HEADSET,
            level=level,
            charging=charging,
            source="HyperX 电量",
            transport="2.4G 接收器",
            raw={"phys": phys, "state": "正常" if level is not None else "充电中"},
            vid_pid=f"{vid:04X}:{pid:04X}",
        ))
    if debug is not None:
        debug.append(f"[HyperX] 命中 {len(devices)} 台")
    return devices
