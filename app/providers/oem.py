# -*- coding: utf-8 -*-
"""按芯片方案读电量，不按品牌白名单。

同一套只读查询覆盖一整批贴牌：Compx 的 17 字节帧、中颖/万灵那条
特征报告、雷蛇 0x07/0x80、华硕 12 07、雷柏主动上报、VAXEE、
八位堂和索尼手柄的标准输入报告。帧对不上就跳过，不显示假电量。
"""
from __future__ import annotations

import time

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, HEADSET, KEYBOARD, MOUSE, UNKNOWN
from providers import proto
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth, phys_token

# 查询没有得到合法应答时，短时间内不再打开它。手动刷新会绕过。
_FAIL: dict[tuple, float] = {}
_FAIL_FOR = 90.0

_FEATURE83_VIDS = {0x258A, 0x36A7, 0x373E, 0x33E4, 0x37B0, 0x2023}
_MCHOSE_VIDS = {0x2023, 0x3837, 0x5253, 0xA8A5}
_SONY_PIDS = {0x0CE6, 0x0DF2, 0x05C4, 0x09CC, 0x0BA0}


def _cooled(key: tuple, force: bool) -> bool:
    if force:
        return False
    return time.monotonic() < _FAIL.get(key, 0.0)


def _mark_fail(key: tuple) -> None:
    _FAIL[key] = time.monotonic() + _FAIL_FOR


def _kind(members: list[dict], name: str) -> str:
    usages = {(i.get("usage_page") or 0, i.get("usage") or 0) for i in members}
    low = (name or "").lower()
    if any(k in low for k in ("headset", "headphone", "earbud", "耳机", "耳麦")):
        return HEADSET
    if (0x0001, 0x0002) in usages or any(k in low for k in ("mouse", "鼠标")):
        return MOUSE
    if (0x0001, 0x0006) in usages or any(k in low for k in ("keyboard", "键盘")):
        return KEYBOARD
    if any(k in low for k in ("controller", "gamepad", "手柄")):
        return UNKNOWN
    return UNKNOWN


def _product_name(members: list[dict], vid: int, pid: int) -> str:
    generic = ("usb receiver", "2.4g receiver", "2.4g dongle", "wireless receiver",
               "receiver", "dongle", "hid-compliant", "usb 输入设备")
    for info in members:
        product = (info.get("product_string") or "").strip()
        low = product.lower()
        if product and not any(word in low for word in generic):
            return product
    for info in members:
        product = (info.get("product_string") or "").strip()
        if product:
            return f"{product} {vid:04X}:{pid:04X}"
    return f"无线设备 {vid:04X}:{pid:04X}"


def _open(path):
    dev = hid.device()
    dev.open_path(path)
    dev.set_nonblocking(True)
    return dev


def _close(dev) -> None:
    try:
        if dev is not None:
            dev.close()
    except Exception:
        pass


def _drain(dev, limit: int = 8) -> None:
    for _ in range(limit):
        try:
            if not dev.read(64, 1):
                return
        except Exception:
            return


def _instance(path) -> str:
    """同一接口上不同集合的共同前缀。最后一段是集合号，去掉之后才能配对。"""
    token = phys_token(path)
    if "&" in token:
        return token.rsplit("&", 1)[0]
    return token


def _read_until(dev, seconds: float, parse, size: int = 64):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        left = deadline - time.monotonic()
        try:
            raw = dev.read(size, max(1, int(left * 1000)))
        except Exception:
            return None
        if not raw:
            continue
        hit = parse(bytes(raw))
        if hit is not None:
            return hit
    return None


def _read_many(devs, seconds: float, parse, size: int = 64):
    """几条集合轮流听。应答不一定回到写出查询的那条。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for dev in devs:
            try:
                raw = dev.read(size, 30)
            except Exception:
                continue
            if not raw:
                continue
            hit = parse(bytes(raw))
            if hit is not None:
                return hit
    return None


def _feature(dev, payload: bytes, size: int, wait: float = 0.12) -> bytes:
    dev.send_feature_report(payload)
    time.sleep(wait)
    data = dev.get_feature_report(payload[0], size)
    return bytes(data or b"")


def _emit(devices: list[Device], debug, vid, pid, phys, name, kind, level, charging, source) -> None:
    if debug is not None:
        debug.append(f"[{source}] {vid:04X}:{pid:04X} {name!r} 电量={level} 充电={charging}")
    devices.append(Device(
        key=f"oem:{source}:{vid:04x}:{pid:04x}:{phys}",
        name=name,
        kind=kind,
        level=level,
        charging=charging,
        source=source,
        transport="2.4G 接收器",
        raw={"phys": phys, "state": "正常"},
        vid_pid=f"{vid:04X}:{pid:04X}",
    ))


def _try_compx(members, force) -> tuple[float, bool] | None:
    targets = [i for i in members
               if (i.get("usage_page") or 0) == 0xFF02 and (i.get("usage") or 0) == 0x0002]
    if not targets:
        return None
    key = ("compx", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    request = proto.compx_request()
    for info in targets:
        dev = None
        try:
            dev = _open(info["path"])
            _drain(dev)
            dev.write(request)
            # 有的接收器把应答放到另一条 FF01 输入集合上，写的那条读不到。
            readers = [dev]
            extra = []
            instance = _instance(info.get("path"))
            for other in members:
                if other is info:
                    continue
                if (other.get("usage_page") or 0) != 0xFF01:
                    continue
                if _instance(other.get("path")) != instance:
                    continue
                try:
                    handle = _open(other["path"])
                except Exception:
                    continue
                extra.append(handle)
                readers.append(handle)
            tenths = (info.get("vendor_id") or 0) == 0x25A7
            try:
                hit = _read_many(readers, 0.45,
                                 lambda raw: proto.parse_compx(raw, tenths=tenths), 32)
            finally:
                for handle in extra:
                    _close(handle)
            if hit is not None:
                return hit
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_feature83(members, vid, force) -> tuple[float, bool] | None:
    if vid not in _FEATURE83_VIDS and vid not in _MCHOSE_VIDS:
        return None
    targets = [i for i in members if (i.get("usage_page") or 0) >= 0xFF00]
    if not targets:
        return None
    key = ("f83", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    request = proto.feature83_request()
    for info in targets:
        dev = None
        try:
            dev = _open(info["path"])
            data = _feature(dev, request, 65, 0.12)
            hit = proto.parse_feature83(data)
            if hit is not None:
                return hit
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_razer(members, vid, force) -> tuple[float, bool] | None:
    if vid != 0x1532:
        return None
    # 毒蝰这类 2.4G 鼠标把 90 字节电量报告放在鼠标集合上，不在厂商页。
    vendor = [i for i in members if (i.get("usage_page") or 0) >= 0xFF00]
    mouse = [i for i in members
             if (i.get("usage_page") or 0, i.get("usage") or 0) == (0x0001, 0x0002)]
    targets = vendor + [i for i in mouse if i not in vendor]
    if not targets:
        targets = members[:2]
    key = ("razer", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    for info in targets[:4]:
        dev = None
        try:
            dev = _open(info["path"])
            level = None
            for tx in (0x1F, 0xFF, 0x3F, 0x9F):
                data = _feature(dev, proto.razer_feature(tx, 0x80), 91, 0.08)
                level = proto.parse_razer_battery(data)
                if level is None:
                    continue
                charging = False
                charge = _feature(dev, proto.razer_feature(tx, 0x84), 91, 0.08)
                flag = proto.parse_razer_charging(charge)
                if flag is not None:
                    charging = flag
                return level, charging
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_asus(members, vid, force) -> tuple[float, bool] | None:
    if vid != 0x0B05:
        return None
    targets = [i for i in members if (i.get("usage_page") or 0) >= 0xFF00]
    if not targets:
        return None
    key = ("asus", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    for info in targets[:4]:
        dev = None
        try:
            dev = _open(info["path"])
            for command in (0x07, 0x01):
                for report_id in (0x00, 0x03, 0x02, 0x01):
                    buf = bytes([report_id, 0x12, command]) + bytes(61)
                    _drain(dev)
                    try:
                        dev.write(buf)
                    except Exception:
                        continue
                    hit = _read_until(dev, 0.2, proto.parse_asus, 64)
                    if hit is not None:
                        return hit
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_rapoo(members, vid, force) -> tuple[float, bool] | None:
    if vid != 0x24AE:
        return None
    targets = [i for i in members if (i.get("usage_page") or 0) >= 0xFF00] or members[:1]
    key = ("rapoo", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    for info in targets[:2]:
        dev = None
        try:
            dev = _open(info["path"])
            hit = _read_until(dev, 1.6, proto.parse_rapoo, 32)
            if hit is not None:
                return hit
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_vaxee(members, vid, force) -> tuple[float, bool] | None:
    if vid != 0x3057:
        return None
    targets = [i for i in members if (i.get("usage_page") or 0) == 0xFF05]
    if not targets:
        return None
    key = ("vaxee", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    for info in targets[:2]:
        dev = None
        try:
            dev = _open(info["path"])
            for _ in range(2):
                data = _feature(dev, proto.vaxee_request(0x0B), 64, 0.15)
                raw = proto.parse_vaxee(data, 0x0B)
                if raw is None or not 0 <= raw <= 20:
                    time.sleep(0.25)
                    continue
                charge = _feature(dev, proto.vaxee_request(0x10), 64, 0.1)
                flag = proto.parse_vaxee(charge, 0x10)
                return float(raw * 5), bool(flag)
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_ajazz(members, vid, force) -> tuple[float, bool] | None:
    if vid != 0x3151:
        return None
    targets = [i for i in members if (i.get("usage_page") or 0) >= 0xFF00]
    if not targets:
        return None
    key = ("ajazz", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None
    poll = bytes([0xF7]) + bytes(31)
    for info in targets[:2]:
        dev = None
        try:
            dev = _open(info["path"])
            _drain(dev)
            dev.write(poll)
            level = _read_until(dev, 0.6, proto.parse_ajazz_status, 32)
            if level is not None:
                return level, False
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def _try_gamepad(members, vid, pid, force) -> tuple[float, bool] | None:
    sony = vid == 0x054C and pid in _SONY_PIDS
    eight = vid == 0x2DC8
    if not sony and not eight:
        return None
    targets = [i for i in members
               if (i.get("usage_page") or 0) in (0x0001, 0xFF00)]
    if not targets:
        targets = members[:1]
    key = ("pad", phys_token(targets[0]["path"]))
    if _cooled(key, force):
        return None

    def _parse(data: bytes):
        if sony and pid in (0x0CE6, 0x0DF2):
            return proto.parse_dualsense(data)
        if sony:
            return proto.parse_ds4(data)
        return proto.parse_8bitdo(data)

    for info in targets[:2]:
        dev = None
        try:
            dev = _open(info["path"])
            hit = _read_until(dev, 0.35, _parse, 128)
            if hit is not None:
                return hit
        except Exception:
            continue
        finally:
            _close(dev)
    _mark_fail(key)
    return None


def scan_oem(debug: list | None = None, force: bool = False) -> list[Device]:
    if hid is None:
        return []
    infos = hid_devices()

    groups: dict[tuple, list[dict]] = {}
    for info in infos:
        path = info.get("path")
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not path or not vid or is_bluetooth(path):
            continue
        groups.setdefault((vid, pid, phys_token(path)), []).append(info)

    devices: list[Device] = []
    probes = (
        ("Compx 电量", lambda m, v, p: _try_compx(m, force)),
        ("厂商电量", lambda m, v, p: _try_feature83(m, v, force)),
        ("Razer 电量", lambda m, v, p: _try_razer(m, v, force)),
        ("华硕 电量", lambda m, v, p: _try_asus(m, v, force)),
        ("雷柏 电量", lambda m, v, p: _try_rapoo(m, v, force)),
        ("VAXEE 电量", lambda m, v, p: _try_vaxee(m, v, force)),
        ("怒喵 电量", lambda m, v, p: _try_ajazz(m, v, force)),
        ("手柄电量", lambda m, v, p: _try_gamepad(m, v, p, force)),
    )
    for (vid, pid, phys), members in groups.items():
        name = _product_name(members, vid, pid)
        kind = _kind(members, name)
        for source, fn in probes:
            try:
                hit = fn(members, vid, pid)
            except Exception as exc:
                if debug is not None:
                    debug.append(f"[{source}] {vid:04X}:{pid:04X} 异常: {exc}")
                continue
            if not hit:
                continue
            level, charging = hit
            _emit(devices, debug, vid, pid, phys, name, kind, level, charging, source)
            break
    if debug is not None:
        debug.append(f"[芯片组] 命中 {len(devices)} 台")
    return devices
