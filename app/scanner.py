# -*- coding: utf-8 -*-
"""扫描调度与结果合并：多通道 -> 统一设备列表。

通道清单、来源判定、保留时长与合并权重都在 `providers/registry.py`，
这里只负责并发跑一遍、按优先级去重、维护"读不到时沿用上次读数"的缓存。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from config import Config
from model import UNKNOWN, Device
from providers import hidlist, registry

MAX_MISS = 3  # 连续失败几次后不再显示，避免闪断


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

        # 通道之间不互相等结果。线程只留 3 条：hidapi 自己有全局锁，
        # 开得再多也不会真的同时读设备，只会在点刷新时多占一截栈内存。
        # HID 清单在进线程池之前只枚举一次。
        logs: list[list[str]] = []
        with hidlist.shared(), ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for channel in registry.CHANNELS:
                local = [] if with_debug else None
                futures.append((channel.label, local,
                                pool.submit(channel.run, local, force)))
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

        # 本工具只管 2.4G / USB 有线。HID++ 可能把蓝牙连接的罗技设备报上来，
        # 这里兜一道。扫描源头也已按总线前缀过滤。
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
            stale = (now - last_ok) > registry.keep_seconds(device)
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
        """同一只接收器被两条通道同时读到，只留一条。

        「已添加」是用户手动试读通过的协议，判据可能和协议包/芯片组重叠。
        专用通道那一条能拿到型号名、充电位与慢协议窗口，是更完整的一份；
        同一条接收器（VID:PID + 实例）已经在别处读到，就不再列第二行。
        """
        native = {(d.vid_pid, (d.raw or {}).get("phys")) for d in devices
                  if registry.is_vendor(d) and not (d.source or "").startswith("已添加")
                  and (d.raw or {}).get("phys")}
        if not native:
            return devices
        kept: list[Device] = []
        for d in devices:
            if ((d.source or "").startswith("已添加")
                    and (d.vid_pid, (d.raw or {}).get("phys")) in native):
                if debug:
                    debug.append(f"[合并] {d.name} 已被专用通道读同一条接收器，已添加副本丢弃")
                continue
            kept.append(d)
        return kept

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
            score_new = registry.score(device)
            score_old = registry.score(existing)
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


