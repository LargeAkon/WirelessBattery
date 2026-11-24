# -*- coding: utf-8 -*-
"""已添加设备：读「添加设备」窗口里手动试读通过、写进配置目录的协议。

为什么只读外置：内置那批协议不再自动挨个试（逐型号实现已经在协议包里，
按 VID:PID 再猜一遍只会和协议包抢同一只接收器）。这里只负责用户亲手加的
那几条 —— 选中型号、试读通过、`profiles.save_external()` 落盘，
之后每次刷新按同一套 read 逻辑读，用户不用再点诊断。

协议文件在 `config_dir()/device_profiles/*.json`，
`profiles.load()` 会把内置表与外置表合并，`source` 不是 "builtin" 的就是用户加的。
"""
from __future__ import annotations

import time

import profiles
from model import GAMEPAD, HEADSET, KEYBOARD, MOUSE, UNKNOWN, Device
from providers import packs, registry
from providers.hidlist import devices as hid_devices
from providers.hidpath import is_bluetooth
from providers.oem import _instance, _kind as _oem_kind, _product_name

# 读不到时的冷却：这台设备根本不吃这条协议，每轮都去等超时只会把刷新拖慢。
# 手动刷新（force=True）绕过。
_FAIL: dict[tuple, float] = {}
_FAIL_FOR = 180.0

_NAME_HINTS = (
    (("耳机", "耳麦", "headset", "headphone", "earbud"), HEADSET),
    (("手柄", "gamepad", "controller", "joypad"), GAMEPAD),
    (("键盘", "keyboard"), KEYBOARD),
    (("鼠标", "mouse"), MOUSE),
)


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


def scan_added(debug: list | None = None, force: bool = False) -> list[Device]:
    infos = hid_devices()
    if not infos:
        return []

    # 只要用户加的那几条，内置表整批不参与
    table = {key: item for key, item in profiles.load().items()
             if item.get("source") != "builtin"}
    if not table:
        return []
    mine = set(table)

    devices: list[Device] = []
    for (vid, pid, instance), members in _groups(infos).items():
        if vid in registry.LIBRARY_SKIP_VIDS:
            continue
        # 协议包里是逐型号验证过的原版实现（带会话、ACK、校验和），
        # 同一组接口被它认领时这里整组让位 —— 两套同时打开会互相抢应答帧。
        try:
            if packs.owns(vid, pid, members, instance):
                if debug is not None:
                    debug.append(f"[已添加] {vid:04X}:{pid:04X} 已由协议包接管，跳过")
                continue
        except Exception:
            pass

        vid_hex, pid_hex = f"{vid:04X}", f"{pid:04X}"
        cands = [p for p in profiles.for_ids(vid_hex, pid_hex) if p["id"] in mine]
        if not cands:
            continue
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
                    debug.append(f"[已添加] {vid_hex}:{pid_hex} {profile['id']} 异常: {exc}")
                _mark_fail(key)
                continue
            if hit["level"] is None:
                _mark_fail(key)
                if debug is not None:
                    raw = hit.get("raw") or b""
                    tail = (" 回包 " + " ".join(f"{b:02X}" for b in raw[:16])) if raw else ""
                    debug.append(
                        f"[已添加] {vid_hex}:{pid_hex} {profile['vendor']} "
                        f"{profile['label']} → {hit.get('error') or '未应答'}{tail}")
                continue

            label = _clean_label(profile["label"]) or product
            devices.append(Device(
                key=f"added:{profile['id']}:{vid:04x}:{pid:04x}:{instance}",
                name=label,
                kind=_kind(profile, members, label),
                level=hit["level"],
                charging=hit["charging"],
                source=f"已添加·{profile['vendor']}",
                transport="2.4G 接收器",
                raw={"phys": instance, "state": "正常", "profile": profile["id"]},
                vid_pid=f"{vid_hex}:{pid_hex}",
            ))
            if debug is not None:
                debug.append(
                    f"[已添加] {vid_hex}:{pid_hex} {label} 电量={hit['level']:.0f}% "
                    f"充电={hit['charging']} 协议={profile['id']}")
            break

    if debug is not None:
        debug.append(f"[已添加] 命中 {len(devices)} 台")
    return devices
