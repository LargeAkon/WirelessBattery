# -*- coding: utf-8 -*-
"""协议库通道：按内置的 57 条厂商协议读电量。

原来每个品牌都在 `oem.py` 里写一个探针函数，加一个牌子要改代码重新打包。
这里改成读 `profiles_data` 里的协议表，一条协议描述「发什么帧、取第几字节」：
凌豹、狼蛛、LEOBOB、前行者、多彩、HECATE、水月雨、高斯、CHERRY、北通、
钛度、IMECOO、CROCIRIS、Pulsar、Scyrox、Hitscan、西伯利亚、寸渊影弑……
这些原本全都没有，现在加进来不用改任何 Python 逻辑。

与 `oem.py` 的分工：oem 按**芯片方案**扫（不看 VID/PID，Compx、0x83、
Nordic 这类公版谁贴牌都能中）；这里按**品牌精确 ID**扫（同一颗公版接收器
上不同型号的差异只有帧里的型号码或另一个字节）。两边都命中时，扫描器会
按「同一只接收器只留一条读数最好的」合并，不会出现两行。
"""
from __future__ import annotations

import time

import profiles
from model import GAMEPAD, HEADSET, KEYBOARD, MOUSE, UNKNOWN, Device
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth
from providers.oem import _instance, _kind as _oem_kind, _product_name

# 读不到时的冷却：这台设备根本不吃这套协议，每轮都去等超时只会把刷新拖慢。
# 手动刷新（force=True）绕过。
_FAIL: dict[tuple, float] = {}
_FAIL_FOR = 180.0

# 这些协议在我们这里已经有专门的通道，而且做得更全（多步协商 / 慢协议 /
# 长时间窗口）。放进来只会和原通道抢同一只接收器，读出来还是一个数。
_NATIVE = {
    "atk-vxe-nordic54",          # providers/oem.py _try_nordic54
    "compx-ff02-17b",            # providers/oem.py _try_compx（含 17 字节与 10 档两种）
    "mchose-g7",                 # providers/oem.py _try_mchose_g7
    "vaxee-3057",                # providers/oem.py _try_vaxee
    "hyperx-cloud2-wireless",    # providers/hyperx.py
    "hyperx-cloud3-wireless",    # providers/hyperx.py
    "hyperx-alpha2",             # providers/hyperx.py
    "hyperx-cloud-alpha-wireless",
    "rainy75-keyboard",          # providers/evision.py 的 14 秒慢窗口
    "asus-rog-mouse",            # providers/oem.py _try_asus
}

_NAME_HINTS = (
    (("耳机", "耳麦", "headset", "headphone", "earbud"), HEADSET),
    (("手柄", "gamepad", "controller", "joypad"), GAMEPAD),
    (("键盘", "keyboard"), KEYBOARD),
    (("鼠标", "mouse"), MOUSE),
)

# 整个 VID 都被专门通道接管：320F 是 Evision 方案，所有 ATK/VGN/VXE/WOB
# 键盘鼠标都走那条通道（含 14 秒慢窗口）。这里再发一遍别的帧只会白等超时。
_COVERED_VIDS = {0x320F}


def _cooled(key: tuple, force: bool) -> bool:
    return not force and time.monotonic() < _FAIL.get(key, 0.0)


def _mark_fail(key: tuple) -> None:
    _FAIL[key] = time.monotonic() + _FAIL_FOR


def _kind(profile: dict, members: list[dict], name: str) -> str:
    """类型优先看协议名（"凌豹 K98 键盘"比 HID 集合可靠），再看标准集合。"""
    text = f"{profile['label']} {profile['keywords']}".lower()
    for words, kind in _NAME_HINTS:
        if any(word in text for word in words):
            return kind
    return _oem_kind(members, name)


def _clean_label(label: str) -> str:
    """协议名里的括号是链路说明（"VXE V3 NK (2.4G)"），不进设备名。"""
    out, depth = [], 0
    for ch in label:
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out).strip()


def _groups(infos: list[dict]) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = {}
    for info in infos:
        path = info.get("path")
        vid = info.get("vendor_id") or 0
        pid = info.get("product_id") or 0
        if not path or not vid or is_bluetooth(path):
            continue
        out.setdefault((vid, pid, _instance(path)), []).append(info)
    return out


def _resolve(cands: list[dict], members: list[dict], vid_hex: str, pid_hex: str):
    """同一只接收器被多个品牌共用时，按会话 ACK 的型号码选型号。

    3554:FA09 上可能是凌豹 K98、狼蛛 F99 Pro、LEOBOB Hi75c 或迈丛 G75 ——
    读法一样，名字不能瞎猜。读不到型号码就给中性名「VID:PID 无线设备」，
    宁可名字笼统，也不把凌豹叫成狼蛛。
    """
    if len(cands) <= 1:
        return cands, "", None
    vendors = {p["vendor"] for p in cands}
    if not (vendors and len(vendors) > 1) and not any(p.get("model_code") for p in cands):
        return cands, "", None
    paths = [i["path"] for i in members
             if (i.get("usage_page") or 0) == 0xFF02 and (i.get("usage") or 0) == 0x0002]
    code = profiles.read_model_code(paths) if paths else None
    if code is not None:
        for profile in cands:
            if profile.get("model_code") == code:
                return [profile], "", code
    return cands, f"{vid_hex}:{pid_hex} 无线设备", code


def scan_profiles(debug: list | None = None, force: bool = False) -> list[Device]:
    infos = hid_devices()
    if not infos:
        return []

    table = profiles.load()
    if not table:
        return []

    devices: list[Device] = []
    for (vid, pid, instance), members in _groups(infos).items():
        if vid in _COVERED_VIDS:
            continue
        vid_hex, pid_hex = f"{vid:04X}", f"{pid:04X}"
        all_cands = [p for p in profiles.for_ids(vid_hex, pid_hex) if p["id"] not in _NATIVE]
        if not all_cands:
            continue
        cands, neutral, code = _resolve(all_cands, members, vid_hex, pid_hex)
        product = _product_name(members, vid, pid)

        for profile in cands[:3]:
            key = (vid, pid, instance, profile["id"])
            if _cooled(key, force):
                continue
            paths = profiles.order_paths(profile, members)
            if not paths:
                continue
            try:
                hit = profiles.read(profile, paths)
            except Exception as exc:
                if debug is not None:
                    debug.append(f"[协议库] {vid_hex}:{pid_hex} {profile['id']} 异常: {exc}")
                _mark_fail(key)
                continue
            if hit["level"] is None:
                _mark_fail(key)
                if debug is not None:
                    raw = hit.get("raw") or b""
                    tail = (" 回包 " + " ".join(f"{b:02X}" for b in raw[:16])) if raw else ""
                    debug.append(
                        f"[协议库] {vid_hex}:{pid_hex} {profile['vendor']} "
                        f"{profile['label']} → {hit.get('error') or '未应答'}{tail}")
                continue

            label = neutral or _clean_label(profile["label"]) or product
            kind = _kind(profile, members, label)
            devices.append(Device(
                key=f"profile:{profile['id']}:{vid:04x}:{pid:04x}:{instance}",
                name=label,
                kind=kind,
                level=hit["level"],
                charging=hit["charging"],
                source=f"协议库·{profile['vendor']}",
                transport="2.4G 接收器",
                raw={"phys": instance, "state": "正常", "profile": profile["id"]},
                vid_pid=f"{vid_hex}:{pid_hex}",
            ))
            if debug is not None:
                model = f" 型号码=0x{code:04X}" if code is not None else ""
                debug.append(
                    f"[协议库] {vid_hex}:{pid_hex} {label} 电量={hit['level']:.0f}% "
                    f"充电={hit['charging']} 协议={profile['id']}{model}")
            break

    if debug is not None:
        debug.append(f"[协议库] 命中 {len(devices)} 台")
    return devices
