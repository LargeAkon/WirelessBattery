# -*- coding: utf-8 -*-
"""扫描调度与结果合并：多通道 -> 统一设备列表。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from config import Config
from model import Device, UNKNOWN
from providers import evision, hid_desc, hidlist, hidpp, hyperx, oem, raw_hid, win_battery, win_pnp, xinput_pad

MAX_MISS = 3  # 连续失败几次后不再显示，避免闪断

# 这些通道读的是设备自己的电量协议。同 VID 的系统条目要让路，
# 但只让给已经读到的那一类：接收器上的键盘不能因为鼠标读到了就被删掉。
_VENDOR_SOURCES = (
    "HID++", "Evision", "Compx", "Razer", "华硕", "雷柏",
    "VAXEE", "迈从", "厂商", "索尼", "8BitDo", "怒喵", "HID 电量", "手柄电量",
    "HyperX",
)


class Scanner:
    # key -> (设备, 连续失败次数, 最后一次成功的时间戳)
    #
    # 必须是类级缓存：ScanWorker 每轮都会 new 一个 Scanner，如果挂在实例上，
    # 缓存每轮都从空开始 —— 下面"连续失败 3 次且超过保留时长才移除"的容错
    # 就永远不成立，设备一休眠就直接从列表里消失。
    _cache: dict[str, tuple[Device, int, float]] = {}

    def __init__(self, config: Config):
        self.config = config

    def scan(self, with_debug: bool = False,
             force: bool = False) -> tuple[list[Device], list[str]]:
        debug: list[str] = []
        found: list[Device] = []
        channels = [
            ("Evision", lambda d: evision.scan_evision(d, force=force)),
            ("HID++", lambda d: hidpp.scan_logitech(d, force=force)),
            ("HyperX", lambda d: hyperx.scan_hyperx(d, force=force)),
            ("芯片组", lambda d: oem.scan_oem(d, force=force)),
            ("HID描述符", lambda d: hid_desc.scan_hid_battery(d)),
            ("手柄", lambda d: xinput_pad.scan_xinput(d)),
            ("系统电池", lambda d: win_battery.scan_win_battery(d)),
            ("系统电量", lambda d: win_pnp.scan_windows_battery(d)),
            ("自定义规则", lambda d: raw_hid.scan_custom(
                self.config.get("custom_rules") or [], d)),
        ]

        # 通道之间不互相等结果。线程只留 3 条：hidapi 自己有全局锁，
        # 开得再多也不会真的同时读设备，只会在点刷新时多占一截栈内存。
        # HID 清单在进线程池之前只枚举一次。
        logs: list[list[str]] = []
        with hidlist.shared(), ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for label, fn in channels:
                local = [] if with_debug else None
                futures.append((label, local, pool.submit(fn, local)))
            for label, local, fut in futures:
                try:
                    found.extend(fut.result())
                except Exception as exc:
                    if local is not None:
                        local.append(f"[{label}] 通道异常: {exc}")
                if local:
                    logs.append(local)
        for local in logs:
            debug.extend(local)

        # 硬过滤：永远不可能给出电量的条目一律不进列表。
        # 典型是公版 2.4G 接收器（如 258A 中颖方案），固件里没有电量接口，
        # 列出来只能显示 "--"，用户会把它当成"凭空多出来的幽灵设备"。
        found = [d for d in found
                 if not (d.level is None and (d.raw or {}).get("state") == "无电量接口")]

        # 本工具只管 2.4G / USB 有线。系统通道已按总线前缀挡掉蓝牙，
        # 这里再兜一道：HID++ 可能把蓝牙连接的罗技设备报上来。
        found = [d for d in found if "蓝牙" not in (d.transport or "")]

        found = self._dedupe_channels(found, debug)

        merged = self._merge(found, debug)
        merged = self._apply_prefs(merged)
        merged.sort(key=lambda d: d.sort_key())

        # 失败容错：读不到时沿用上次有效读数。
        #
        # 只按"连续失败 3 次"就移除太激进：无线鼠标闲置十几分钟会进深度休眠，
        # HID++ 请求全部超时，于是设备从列表里凭空消失 —— 用户看到的是"软件丢了设备"，
        # 实际上只是它在省电。所以再加一道时间闸：既要连续失败 MAX_MISS 次，
        # 又要距上次成功超过保留时长，才真正移除。保留时长按通道区分，罗技最久。
        alive: list[Device] = []
        seen_names: set[str] = set()
        current_keys = {d.key for d in merged}
        now = time.monotonic()
        for device in merged:
            self._cache[device.key] = (device, 0, now)
            alive.append(device)
            seen_names.add((device.name or "").lower())
        for key, (device, miss, last_ok) in list(self._cache.items()):
            if key in current_keys:
                continue
            miss += 1
            stale = (now - last_ok) > _keep_seconds(device)
            if miss >= MAX_MISS and stale:
                self._cache.pop(key, None)
                continue
            name_key = (device.name or "").lower()
            if name_key in seen_names:
                self._cache.pop(key, None)
                continue
            # 标记成"超时"：界面上要能看出这是上次的读数，不是刚读到的
            raw = dict(device.raw or {})
            raw["state"] = "超时"
            device.raw = raw
            self._cache[key] = (device, miss, last_ok)
            alive.append(device)
            seen_names.add(name_key)

        alive.sort(key=lambda d: d.sort_key())
        return alive, debug
    # ---------- 跨通道去重 ----------
    def _dedupe_channels(self, devices: list[Device], debug: list[str]) -> list[Device]:
        """同一个物理设备会被多条通道同时看到，这里只留读数最好的一条。

        两种重复：
        1. 「系统电池」与「系统设备电量」读的是同一批设备 —— instance 相同就合并，
           留电池类那条：它能给出充放电状态，读数也更实时。
        2. 厂商协议（HID++ / Evision）能读到的设备，系统通道那条必然重复。
           厂商通道名字是型号、读数直接来自固件，优先保留。

        第 2 条按 VID:PID 加设备类型判断。接收器上的键盘不会因为
        鼠标已经被厂商通道读到就被一起丢掉。
        """
        battery_instances = {
            (d.raw or {}).get("instance")
            for d in devices if d.source == "系统电池" and (d.raw or {}).get("instance")
        }
        kept: list[Device] = []
        for d in devices:
            if d.source == "系统设备电量":
                inst = (d.raw or {}).get("instance")
                if inst and inst in battery_instances:
                    if debug:
                        debug.append(f"[合并] {d.name} 与系统电池通道重复，已丢弃")
                    continue
            kept.append(d)

        vendor_kinds: dict[str, set[str]] = {}
        for d in kept:
            if d.vid_pid and d.level is not None and _is_vendor(d):
                vendor_kinds.setdefault(d.vid_pid, set()).add(d.kind or UNKNOWN)
        result: list[Device] = []
        for d in kept:
            kinds = vendor_kinds.get(d.vid_pid or "")
            if (d.source in ("系统电池", "系统设备电量") and kinds
                    and (UNKNOWN in kinds or d.kind in kinds or d.kind == UNKNOWN)):
                if debug:
                    debug.append(
                        f"[合并] {d.name} 已被厂商通道读到（{d.vid_pid}），系统通道重复项丢弃")
                continue
            result.append(d)
        return result

    # ---------- 合并去重 ----------
    def _merge(self, devices: list[Device], debug: list[str]) -> list[Device]:
        by_name: dict[str, Device] = {}
        for device in devices:
            name = (device.name or "").strip().lower()
            if not name:
                continue
            # 名字相同但不是同一只接收器时都要留下。两只都叫
            # “符合 HID 标准的鼠标”不能并成一台。
            raw = device.raw or {}
            token = raw.get("phys") or raw.get("instance") or device.key
            name_key = f"{device.vid_pid}|{token}|{name}"
            existing = by_name.get(name_key)
            if existing is None:
                by_name[name_key] = device
                continue
            # 保留信息更完整的一条
            score_new = _score(device)
            score_old = _score(existing)
            if score_new > score_old:
                by_name[name_key] = device
            elif debug:
                debug.append(f"[合并] 重复设备 {device.name} 已去重")
        return list(by_name.values())

    # ---------- 用户偏好与类型纠偏 ----------
    def _apply_prefs(self, devices: list[Device]) -> list[Device]:
        overrides = self.config.get("overrides") or {}
        for device in devices:
            ov = overrides.get(device.key) or {}
            if not ov:
                # 兼容：按名称匹配的偏好
                for _, entry in overrides.items():
                    if entry.get("name") and entry["name"] == device.name:
                        ov = entry
                        break
            if ov.get("kind"):
                device.kind = ov["kind"]
            if ov.get("name"):
                device.name = ov["name"]
            if not device.kind:
                device.kind = UNKNOWN
        return devices


def _is_vendor(device: Device) -> bool:
    return (device.source or "").startswith(_VENDOR_SOURCES)


def _keep_seconds(device: Device) -> float:
    """设备读不到时保留上次读数多久（秒）。"""
    src = device.source or ""
    if src.startswith("HID++"):
        # 罗技设备闲置约 15 分钟进深度休眠，期间完全不应答 HID++。
        # 保留 10 分钟：既覆盖典型休眠，又不至于拔掉后长时间挂着幽灵设备。
        return 600.0
    if src.startswith(("Evision", "Compx", "Razer", "华硕", "雷柏", "VAXEE", "厂商", "迈从", "HyperX")):
        return 300.0
    return 180.0


def _score(device: Device) -> int:
    score = 0
    if device.level is not None:
        score += 4
    if device.kind != UNKNOWN:
        score += 2
    if _is_vendor(device):
        score += 2
    if device.source.startswith(
            ("HID++", "Evision", "Compx", "Razer", "华硕", "雷柏", "VAXEE", "厂商", "HyperX")):
        score += 1
    # 同一只鼠标可能同时被"有线直连"和"接收器"看到（插着线充电、无线也还注册着）。
    # 有线这一路是实时直连，接收器那路可能滞后，合并时优先保留有线读数。
    if device.transport.startswith("USB 有线"):
        score += 3
    if device.name and any(ch.isupper() for ch in device.name):
        score += 1
    return score
