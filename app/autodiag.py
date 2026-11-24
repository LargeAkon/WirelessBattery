# -*- coding: utf-8 -*-
"""一键自动诊断：不需要用户认识"端点""页面""用法"这些词。

诊断页原来要求"在端点表里找到 ★ 那一行 → 复制 → 粘贴 → 点识别"，
对只想看电量的普通用户门槛太高 —— 他们连哪一行该复制都判断不了。
这里改成一条流水线，点一下跑完：

    1. 把已实现的读取通道全跑一遍（HID++ / Evision / 芯片组 / 标准 HID /
       XInput / 系统电池 / 已有规则）；
    2. 枚举当前所有 HID 端点，按接收器分组，挑出还没读到电量的那些；
    3. 对每台没读到的接收器，在它的厂商端点上被动听 2 秒，
       找到"稳定落在 1~100"的字节就自动存成规则、直接加进列表；
    4. 读不到的把原因留下（端点被占用 / 没有任何上报 / 有上报但找不到电量字节），
       界面只显示这一句，用户照着回一句就行。

两条硬约束：
- 全程不做主动盲写。私有协议帧格式猜错可能让接收器掉线（Rainy75 那次已经
  验证过风险），所以只被动听，不往未知端点乱发命令。
- 找不到就写"没找到"，绝不拿一个凑出来的百分比充数。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from model import UNKNOWN, Device
from providers import hidlist, raw_hid
from providers.oem import _kind as _oem_kind

PROBE_SECONDS = 2.0   # 每台接收器被动听多久
MAX_PROBES = 8        # 一次最多听几台，避免插一排接收器时一直转圈

# 接收器会挂这些标准集合，电影摄像头 / 音频设备不会。
_PERIPHERAL = {
    (0x0001, 0x0001), (0x0001, 0x0002), (0x0001, 0x0004),
    (0x0001, 0x0005), (0x0001, 0x0006), (0x0001, 0x0007),
    (0x000C, 0x0001),
}

# 名字里出现这些就是无线外设，不用再看别的条件
_WIRELESS_HINTS = ("receiver", "2.4g", "2.4 ghz", "2.4 GHz", "wireless", "无线",
                   "dongle", "接收器", "接收")
# 主板灯控、声卡、摄像头、虚拟设备这些也挂厂商页，但跟电量无关。
# 不挡掉的话，用户点一次诊断会看到一屏"读不到电量"，比不给结果更糟。
_SKIP_HINTS = ("led", "aura", "rgb", "light", "audio", "microphone", "headphone jack",
               "camera", "webcam", "touchpad", "touch pad", "trackpad", "sensor",
               "vhf", "virtual", "hub", "dock", "printer", "scanner",
               "bluetooth", "蓝牙")

Progress = Callable[[str, int], None]


def _say(progress: Progress | None, text: str, pct: int) -> None:
    if progress is not None:
        try:
            progress(text, pct)
        except Exception:
            pass


def _vid_pid(ep: dict) -> str:
    return f"{ep.get('vendor_id') or 0:04X}:{ep.get('product_id') or 0:04X}"


def group_endpoints(eps: list[dict]) -> dict[str, list[dict]]:
    """按 VID:PID 分组。同一只接收器会挂鼠标口、键盘口、厂商口好几条。"""
    out: dict[str, list[dict]] = {}
    for ep in eps:
        out.setdefault(_vid_pid(ep), []).append(ep)
    return out


def _vendor_eps(eps: list[dict]) -> list[dict]:
    """厂商自定义页（0xFF00 往上）才有私有电量帧，标准页只是输入报文。"""
    pool = [e for e in eps if (e.get("usage_page") or 0) >= 0xFF00]
    # ★ 行优先；同一页里长报文（用法 0x0002）优先
    pool.sort(key=lambda e: (not e.get("recommend"),
                             (e.get("usage") or 0) != 0x0002,
                             e.get("interface") or 0))
    return pool


def _is_candidate(eps: list[dict]) -> bool:
    """像不像一台 2.4G 外设的接收器。

    判据（同时要满足）：
    1. 挂着厂商自定义页 —— 私有电量帧只可能从这里出来；
    2. 名字像无线设备，或者同时挂着鼠标 / 键盘 / 手柄这类标准集合；
    3. 名字不是灯控、声卡、摄像头、虚拟设备。

    挡掉这些是为了"傻瓜式"：用户点一次诊断，不该看到一个主板 RGB 灯控
    和虚拟 HID 驱动的"读不到电量"，那只会让人以为软件坏了。
    """
    if not any((e.get("usage_page") or 0) >= 0xFF00 for e in eps):
        return False
    name = " ".join((e.get("product") or "") for e in eps).lower()
    if any(word in name for word in _SKIP_HINTS):
        return False
    if any(word in name for word in _WIRELESS_HINTS):
        return True
    return any((e.get("usage_page") or 0, e.get("usage") or 0) in _PERIPHERAL
               for e in eps)


def _display_name(eps: list[dict], vid_pid: str) -> str:
    generic = ("usb receiver", "2.4g receiver", "2.4g dongle", "wireless receiver",
               "receiver", "dongle", "hid-compliant", "输入设备")
    named = [(e.get("product") or "").strip() for e in eps]
    named = [n for n in named if n]
    for n in named:
        low = n.lower()
        if not any(word in low for word in generic):
            return n
    if named:
        return f"{named[0]} {vid_pid}"
    return f"无线接收器 {vid_pid}"


def _known_vidpids(devices: list[Device]) -> set[str]:
    known: set[str] = set()
    for d in devices or []:
        if d.vid_pid:
            known.add(d.vid_pid.upper())
        # 规则设备的 key 是 rule:vid:pid:name，vid/pid 是十进制
        if (d.key or "").startswith("rule:"):
            parts = d.key.split(":")
            if len(parts) >= 3:
                try:
                    known.add(f"{int(parts[1]):04X}:{int(parts[2]):04X}")
                except ValueError:
                    pass
    return known


def _kind_of(eps: list[dict], name: str) -> str:
    members = [{"usage_page": e.get("usage_page"), "usage": e.get("usage")}
               for e in eps]
    return _oem_kind(members, name)


def _same_match(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k)
               for k in ("vendor_id", "product_id", "usage_page", "usage"))


def _save_rule(config, rule: dict) -> bool:
    """存规则。同一组端点已经存过就覆盖，避免每次诊断叠一条。"""
    rules = list(config.get("custom_rules") or [])
    match = rule.get("match") or {}
    kept = [r for r in rules if not _same_match(r.get("match") or {}, match)]
    kept.append(rule)
    config.set("custom_rules", kept)
    return len(kept) != len(rules)


def _pick_candidate(res: dict) -> dict | None:
    """从被动采到的字节里挑一个最像电量的。

    判据和人工识别时一致：稳定不跳、样本至少 3 条、取值落在 1~100。
    """
    cands = [c for c in (res.get("candidates") or [])
             if c.get("stable") and c.get("samples", 0) >= 3
             and 1 <= (c.get("value") or 0) <= 100]
    if not cands:
        return None
    # 同一帧里可能有多个稳定的小整数（模式位、通道号），电量一般是其中最大
    # 的那个百分比；取值相同时取靠前的字节。这条判据与人工识别时一致。
    cands.sort(key=lambda c: (-c.get("value", 0), c.get("byte", 0)))
    return cands[0]


def _fix_kinds(devices: list[Device], groups: dict[str, list[dict]]) -> int:
    """图标落成"未知"的，用同一只接收器的标准集合补上类型。"""
    fixed = 0
    for d in devices:
        if d.kind != UNKNOWN or not d.vid_pid:
            continue
        eps = groups.get(d.vid_pid.upper())
        if not eps:
            continue
        kind = _kind_of(eps, d.name)
        if kind != UNKNOWN:
            d.kind = kind
            fixed += 1
    return fixed


def run(config, progress: Progress | None = None,
        stop: threading.Event | None = None,
        existing: list[Device] | None = None) -> dict:
    """跑完整诊断。返回给界面直接渲染的字典。

    existing：界面上已经显示过的设备。传进来可以少跑一次扫描。
    """
    started = time.monotonic()
    result: dict = {
        "devices": [],      # 读到电量的设备（含本次自动加进来的）
        "failed": [],       # 有端点但读不到：[{name, vid_pid, reason}]
        "rules": 0,         # 本次新存下的规则条数
        "fixed": 0,         # 补全类型的设备数
        "endpoints": 0,
        "receivers": 0,
        "seconds": 0.0,
        "logs": [],
        "samples": [],      # 被动采样到的原始帧，导出报告用
        "stopped": False,
    }
    samples: list[str] = result["samples"]

    if stop is not None and stop.is_set():
        result["stopped"] = True
        return result

    # 整轮共用一份 HID 清单：hid.enumerate() 一次就够，通道再多也不重复列举
    with hidlist.shared():
        eps = raw_hid.describe_endpoints()
        result["endpoints"] = len(eps)
        groups = group_endpoints(eps)

        _say(progress, "正在读取已支持的设备…", 10)
        devices: list[Device] = list(existing or [])
        if not devices:
            from scanner import Scanner
            try:
                devices, debug = Scanner(config).scan(with_debug=True, force=True)
                result["logs"].extend(debug)
            except Exception as exc:
                result["logs"].append(f"扫描异常: {type(exc).__name__}: {exc}")
                devices = []

        result["fixed"] = _fix_kinds(devices, groups)

        if stop is not None and stop.is_set():
            result["devices"] = devices
            result["stopped"] = True
            return result

        # ---------- 还没读到的接收器 ----------
        known = _known_vidpids(devices)
        pending: list[tuple[str, list[dict]]] = []
        for vid_pid, group_eps in groups.items():
            if vid_pid.upper() in known:
                continue
            if not _is_candidate(group_eps):
                continue
            pending.append((vid_pid, group_eps))
        result["receivers"] = len(pending)

        todo = pending[:MAX_PROBES]
        skipped = pending[MAX_PROBES:]
        for index, (vid_pid, group_eps) in enumerate(todo):
            if stop is not None and stop.is_set():
                result["stopped"] = True
                break
            name = _display_name(group_eps, vid_pid)
            pct = 30 + int(60 * index / max(1, len(todo)))
            _say(progress, f"正在识别 {name}（{index + 1}/{len(todo)}）…", pct)

            vendor = _vendor_eps(group_eps)
            if not vendor:
                result["failed"].append({
                    "name": name,
                    "vid_pid": vid_pid,
                    "reason": "只有标准输入端点，没有厂商协议端点（这类设备不对外报电量）",
                })
                continue

            hit = None
            error = ""
            no_report = True
            for ep in vendor[:2]:
                try:
                    res = raw_hid.sniff_candidates(ep["path"], PROBE_SECONDS, "")
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    continue
                if res.get("error"):
                    error = res["error"]
                    samples.append(f"{vid_pid} 页=0x{(ep.get('usage_page') or 0):04X} "
                                   f"用法=0x{(ep.get('usage') or 0):04X} → {error}")
                    continue
                if (res.get("total") or 0) > 0:
                    no_report = False
                best = _pick_candidate(res)
                # 原始帧留在报告里：读到了要能核对字节位置，读不到要能照着补协议。
                if res.get("reports"):
                    samples.append(f"{vid_pid} 页=0x{(ep.get('usage_page') or 0):04X} "
                                   f"用法=0x{(ep.get('usage') or 0):04X} "
                                   f"→ {res.get('total', 0)} 帧")
                    for rid, hex_text in res["reports"][:4]:
                        samples.append(f"    rid={rid}  {hex_text}")
                if best is not None:
                    hit = (ep, best)
                    break

            if hit is None:
                if error:
                    reason = "接收器没有开放电量通道（固件里没有电量数据）"
                elif no_report:
                    reason = ("厂商通道 2 秒内没有任何上报（这类设备只在被主动查询时才回答，"
                              "需要按它的协议补一条指令）")
                else:
                    reason = "有上报，但报文里找不到稳定的电量字节"
                result["logs"].append(f"[自动识别] {name} {vid_pid} 未读到：{reason}"
                                      + (f"（原始错误：{error}）" if error else ""))
                result["failed"].append({"name": name, "vid_pid": vid_pid, "reason": reason})
                continue

            ep, best = hit
            label = name
            kind = _kind_of(group_eps, label)
            rule = {
                "name": label,
                "kind": kind,
                "match": {
                    "vendor_id": ep.get("vendor_id"),
                    "product_id": ep.get("product_id"),
                    "usage_page": ep.get("usage_page"),
                    "usage": ep.get("usage"),
                },
                "query": "",
                "report_id": best["report_id"],
                "byte": best["byte"],
                "transport": "2.4G 接收器",
                "timeout": PROBE_SECONDS,
            }
            if _save_rule(config, rule):
                result["rules"] += 1
            devices.append(Device(
                key=f"rule:{ep.get('vendor_id')}:{ep.get('product_id')}:{label}",
                name=label,
                kind=kind,
                level=float(best["value"]),
                source="自动识别",
                transport="2.4G 接收器",
                vid_pid=vid_pid,
            ))
            result["logs"].append(
                f"[自动识别] {label} {vid_pid} 报文 0x{best['report_id']:02X} "
                f"第 {best['byte']} 字节 = {best['value']}%")

        for vid_pid, group_eps in skipped:
            result["failed"].append({
                "name": _display_name(group_eps, vid_pid),
                "vid_pid": vid_pid,
                "reason": f"这次检查的接收器太多，只看了前 {MAX_PROBES} 只，点一次重新诊断即可",
            })

    result["devices"] = devices
    result["seconds"] = time.monotonic() - started
    return result


# ---------------- 文案 ----------------
def _count(result: dict) -> tuple[int, int]:
    return len(result.get("devices") or []), len(result.get("failed") or [])


def summary(result: dict) -> str:
    """底部一行结论。宁可短，不要长。"""
    ok, bad = _count(result)
    seconds = result.get("seconds") or 0.0
    if result.get("stopped"):
        return "已停止"
    if not result.get("endpoints"):
        return "没有检测到任何 USB HID 设备，确认接收器插好了再点一次"
    if ok and not bad:
        return f"识别到 {ok} 台设备，用时 {seconds:.1f} 秒"
    if ok and bad:
        return f"识别到 {ok} 台设备，另有 {bad} 台读不到电量（下方写了原因）"
    if bad:
        return f"当前 {bad} 台接收器都读不到电量，原因见下表"
    return "没有发现无线外设，确认接收器插好、设备已开机再试一次"


__all__ = ["run", "summary", "group_endpoints"]
