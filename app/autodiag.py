# -*- coding: utf-8 -*-
"""一键自动诊断：不需要用户认识"端点""页面""用法"这些词。

诊断页原来要求"在端点表里找到 ★ 那一行 → 复制 → 粘贴 → 点识别"，
对只想看电量的普通用户门槛太高 —— 他们连哪一行该复制都判断不了。
这里改成一条流水线，点一下跑完：

    1. 把已实现的读取通道全跑一遍（协议包 / Evision / HID++ / HyperX / 芯片组 /
       已添加协议）；
    2. 枚举当前所有 HID 端点，按接收器分组，挑出还没读到电量的那些；
    3. 给每台没读到的写清原因：没有厂商端点、或者有端点但内置协议没匹配上，
       后一种直接在「添加设备」里选型号试读；
    4. 顺手把图标落成"未知"的设备按标准集合补上类型。

两条硬约束：
- 不往未知端点发任何命令。私有协议帧格式猜错可能让接收器掉线（Rainy75 那次
  已经验证过风险），所以诊断只做读、只做解释。
- 找不到就写"没找到"，绝不拿一个凑出来的百分比充数。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import profiles
from model import UNKNOWN, Device
from providers import hidlist, raw_hid
from providers.oem import _kind as _oem_kind


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


def vendor_endpoints(eps: list[dict]) -> list[dict]:
    """对外的名字：厂商协议端点（诊断页与添加窗口都要用）。"""
    return _vendor_eps(eps)


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
        "fixed": 0,         # 补全类型的设备数
        "endpoints": 0,
        "receivers": 0,
        "seconds": 0.0,
        "logs": [],
        "stopped": False,
    }

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
        # 这里只解释原因，不再被动嗅探、也不再自动存规则：
        # 逐型号/按芯片方案的读取都在 providers 里，猜出来的字节没有验证过，
        # 给了反而是个会跳的假读数。需要补协议的去「添加设备」手动试读。
        known = _known_vidpids(devices)
        for vid_pid, group_eps in groups.items():
            if vid_pid.upper() in known or not _is_candidate(group_eps):
                continue
            name = _display_name(group_eps, vid_pid)
            if _vendor_eps(group_eps):
                reason = ("有厂商端点，但内置协议没匹配上 —— "
                          "在「添加设备」里选型号试读一次即可")
            else:
                reason = "只有标准输入端点，没有厂商协议端点（这类设备不对外报电量）"
            result["logs"].append(f"[诊断] {name} {vid_pid} 未读到：{reason}")
            result["failed"].append({"name": name, "vid_pid": vid_pid, "reason": reason})
        result["receivers"] = len(result["failed"])

    result["devices"] = devices
    result["seconds"] = time.monotonic() - started
    return result


def scan_only(config) -> dict:
    """只跑一遍扫描，不做被动监听。添加设备后刷新列表用（几秒内结束）。"""
    from scanner import Scanner
    devices, debug = Scanner(config).scan(with_debug=True, force=True)
    return {
        "devices": devices, "failed": [], "fixed": 0,
        "endpoints": 0, "seconds": 0.0, "logs": debug, "stopped": False,
    }


# ---------------- 手动添加设备（对应「添加设备」窗口） ----------------

def receivers(known: set[str] | None = None) -> list[dict]:
    """列出可以手动适配的接收器。

    known 传已经读到电量的 VID:PID；这些默认不列，避免用户又加一遍
    （窗口上勾「显示全部」时传空集合即可）。
    """
    known = {k.upper() for k in (known or set())}
    with hidlist.shared():
        eps = raw_hid.describe_endpoints()
    out: list[dict] = []
    for vid_pid, group in group_endpoints(eps).items():
        if vid_pid.upper() in known:
            continue
        if not _is_candidate(group):
            continue
        name = _display_name(group, vid_pid)
        out.append({
            "vid_pid": vid_pid,
            "name": name,
            "kind": _kind_of(group, name),
            "endpoints": group,
            "paths": [e.get("path") for e in _vendor_eps(group) if e.get("path")],
            "guesses": [p["id"] for p in profiles.for_ids(*vid_pid.split(":"))],
        })
    out.sort(key=lambda r: r["name"].lower())
    return out


def protocol_choices() -> list[dict]:
    """「选择品牌型号」下拉的条目。"""
    return profiles.choices()


def _pick_profile(receiver: dict, profile_id: str) -> dict | None:
    if profile_id:
        return profiles.by_id(profile_id)
    guesses = receiver.get("guesses") or []
    if guesses:
        return profiles.by_id(guesses[0])
    return None


def detect(receiver: dict, profile_id: str = "") -> dict:
    """试读：按指定协议问一次，返回结果与给用户看的一句话。"""
    profile = _pick_profile(receiver, profile_id)
    if profile is None:
        return {"ok": False, "level": None, "charging": False, "profile": None,
                "text": "这只接收器没有已知协议，先点「自动探测」"}
    paths = profiles.order_paths(profile, receiver.get("endpoints") or [])
    if not paths:
        return {"ok": False, "level": None, "charging": False, "profile": profile,
                "text": f"没有可用的接口（协议要 0x{profile['match']['usage_page']:04X} 页面）"}
    hit = profiles.read(profile, paths)
    if hit["level"] is None:
        return {"ok": False, "level": None, "charging": False, "profile": profile,
                "text": f"没读到：{hit.get('error') or '设备没有应答'}"}
    text = f"读到 {hit['level']:.0f}%" + ("（充电中）" if hit["charging"] else "")
    return {"ok": True, "level": hit["level"], "charging": hit["charging"],
            "profile": profile, "text": text}


def auto_probe(receiver: dict, progress: Progress | None = None,
               stop: threading.Event | None = None,
               skip: set | None = None,
               budget: float = 12.0) -> dict:
    """自动探测：轮试协议库里的全部模板，两次读数接近才算命中。

    只发「已知厂商查询帧」，不往未知端点乱写 —— 帧猜错可能让接收器掉线。
    一只接收器常同时挂 0xFF00 和 0xFF02 两个厂商页，协议落在哪一页不固定，
    所以逐页试；每页给 `budget` 秒，到点换下一页，不会把窗口卡住。
    """
    eps = vendor_endpoints(receiver.get("endpoints") or [])
    if not eps:
        return {"ok": False, "profile": None, "text": "这只接收器没有厂商协议端点"}

    skip = set(skip or ())
    tried: list[str] = []
    pages: list[tuple[int, int]] = []
    for ep in eps:
        pair = (ep.get("usage_page") or 0, ep.get("usage") or 0)
        if pair not in pages:
            pages.append(pair)

    # 每页还剩多少条没试，条数多的页先试。
    # 之前固定只试 pages[:3]：前三页试完后，每次点击都在空页上跑，
    # 于是"试了 0 条"却还报"还剩 50 条"——那 50 条声明的是别的厂商页，
    # 在这台接收器上根本发不出去，用户永远点不完。现在按剩余量轮换，
    # 并且"还剩多少"只数这台接收器上真正能试的。
    todo: list[tuple[int, int, int]] = []
    reachable: set[str] = set()
    for page, usage in pages:
        ids = [p["id"] for p in profiles.candidates_for(
            page, usage, vid_pid=receiver.get("vid_pid") or "")]
        reachable.update(ids)
        left_ids = [i for i in ids if i not in skip]
        if left_ids:
            todo.append((len(left_ids), page, usage))
    todo.sort(key=lambda item: -item[0])

    for _left, page, usage in todo[:3]:
        if stop is not None and stop.is_set():
            break
        result = profiles.probe(
            receiver.get("endpoints") or [], page, usage,
            stop=stop,
            progress=(lambda text: _say(progress, text, 60)) if progress else None,
            skip=skip, budget=budget,
            vid_pid=receiver.get("vid_pid") or "",
        )
        tried.extend(result.get("tried_ids") or [])
        skip.update(result.get("tried_ids") or [])
        if not result["ok"]:
            continue
        profile = result["profile"]
        text = (f"命中 {profile['vendor']} · {profile['label']}，"
                f"读到 {result['level']:.0f}%" + ("（充电中）" if result["charging"] else ""))
        return {"ok": True, "profile": profile, "level": result["level"],
                "charging": result["charging"], "text": text,
                "usage_page": page, "usage": usage, "tried_ids": tried,
                "remaining": 0}

    left = len(reachable - skip)
    if not reachable:
        text = ("这台接收器的厂商页上没有可试的内置协议 —— "
                "请从上面的型号里手动选一个再「试读」")
    elif left:
        text = (f"试了 {len(tried)} 条还没中，还剩 {left} 条 —— "
                f"再点一次「自动探测」接着试")
    elif tried:
        text = (f"这台接收器能试的 {len(reachable)} 条都试过了，没有一条能读"
                f"（多为私有帧）—— 从上面的型号里选一个再「试读」，或导出报告")
    else:
        text = (f"这台接收器上能试的 {len(reachable)} 条之前都试过了"
                f"—— 从上面的型号里选一个再「试读」，或导出报告")
    return {"ok": False, "profile": None, "text": text, "tried_ids": tried,
            "remaining": left}


def remember(receiver: dict, profile: dict, usage_page: int, usage: int,
             name: str = "", kind: str = "") -> tuple[str, str]:
    """把试读成功的协议固化下来：写外置协议 + 记住名字和类型。

    写的是配置目录 `device_profiles/<id>.json`，下次启动由协议库直接读，
    不需要再点诊断。
    """
    label = (name or "").strip() or profile["label"]
    profiles.save_external(profile, *receiver["vid_pid"].split(":"),
                           usage_page=usage_page, usage=usage, label=label)

    # 设备的 key 由通道生成，这里按同样的规则算一遍，改名才能落到这台设备上
    instance = ""
    for path in receiver.get("paths") or []:
        instance = profiles.device_instance(path)
        break
    key = f"profile:{profile['id']}:{receiver['vid_pid'].split(':')[0].lower()}:" \
          f"{receiver['vid_pid'].split(':')[1].lower()}:{instance}"
    return key, label


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
        return f"识别到 {ok} 台设备 · 另有 {bad} 台读不到，可点「添加设备」指定型号"
    if bad:
        return f"当前 {bad} 台接收器都读不到电量，点「添加设备」可手动指定型号"
    return "没有发现无线外设，确认接收器插好、设备已开机再试一次"


__all__ = ["run", "summary", "group_endpoints"]
