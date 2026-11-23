# -*- coding: utf-8 -*-
"""把"从诊断表里复制出来的端点信息"重新翻译成一个可用的设备。

诊断页里点一下「复制」，得到一行纯文本；粘贴回来点「识别」，这里负责：
    1. 解析出 VID:PID / 页面 / 用法 / 接口 / path；
    2. 在当前系统里找到同一个真实端点（设备可能重插过，path 变了也能靠
       VID:PID + 用法重新定位）；
    3. 依次用内置协议（HID++、Evision）读一次；都不通时被动听 3 秒，
       从上报报文里找出那个"稳定不变、取值 1~100"的字节，生成一条规则。

为什么要绕这一圈：用户看到的是一张端点表，程序需要的是"电量在哪个通道、
哪个字节"。把这一步自动化，换任何新设备都不必再改代码。
"""
from __future__ import annotations

import re

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, HEADSET, KEYBOARD, MOUSE, UNKNOWN
from providers import evision, hidpp, raw_hid

LOGITECH_VID = 0x046D
EVISION_VID = 0x320F


# ---------------- 生成可复制的文本 ----------------
def endpoint_text(ep: dict) -> str:
    """一行纯文本，人能看懂，程序也能解析回来。"""
    page = ep.get("usage_page") or 0
    use = ep.get("usage") or 0
    path = ep.get("path") or b""
    if isinstance(path, bytes):
        path = path.decode("utf-8", "ignore")
    return (f"{ep.get('vendor_id', 0):04X}:{ep.get('product_id', 0):04X} | "
            f"{ep.get('product') or '-'} | "
            f"页面=0x{page:04X} 用法=0x{use:04X} | "
            f"接口={ep.get('interface')} | path={path}")


# ---------------- 解析 ----------------
_VID_PID = re.compile(r"([0-9A-Fa-f]{4})\s*:\s*([0-9A-Fa-f]{4})")
_PAIR = re.compile(
    r"(?:页面|页)\s*[=:]?\s*0x([0-9A-Fa-f]{1,4})[^\n]*?(?:用法)\s*[=:]?\s*0x([0-9A-Fa-f]{1,4})")
_SLASH_PAIR = re.compile(r"0x([0-9A-Fa-f]{1,4})\s*/\s*0x([0-9A-Fa-f]{1,4})")
_IFACE = re.compile(r"接口\s*[=:]?\s*(-?\d+)")
_PATH = re.compile(r"path\s*=\s*(.+?)\s*$", re.I | re.M)


def parse_endpoint(text: str) -> dict | None:
    """宽松解析。支持本程序复制的格式，也支持诊断报告里的端点行。"""
    text = (text or "").strip()
    if not text:
        return None
    m = _VID_PID.search(text)
    if not m:
        return None
    parsed = {
        "vendor_id": int(m.group(1), 16),
        "product_id": int(m.group(2), 16),
        "usage_page": None,
        "usage": None,
        "interface": None,
        "path": None,
    }
    pair = _PAIR.search(text) or _SLASH_PAIR.search(text)
    if pair:
        parsed["usage_page"] = int(pair.group(1), 16)
        parsed["usage"] = int(pair.group(2), 16)
    im = _IFACE.search(text)
    if im:
        parsed["interface"] = int(im.group(1))
    pm = _PATH.search(text)
    if pm:
        parsed["path"] = pm.group(1).strip()
    return parsed


# ---------------- 定位当前端点 ----------------
def _path_text(path) -> str:
    if isinstance(path, bytes):
        return path.decode("utf-8", "ignore")
    return str(path or "")


def resolve(parsed: dict) -> dict | None:
    """在当前系统的 HID 列表里找回这个端点。"""
    if hid is None:
        return None
    from providers.hidlist import devices as hid_devices

    infos = hid_devices()
    if not infos:
        return None

    want_path = parsed.get("path")
    if want_path:
        for info in infos:
            if _path_text(info.get("path")) == want_path:
                return info

    cands = [i for i in infos
             if i.get("vendor_id") == parsed["vendor_id"]
             and i.get("product_id") == parsed["product_id"]]
    if parsed.get("usage_page") is not None:
        cands = [i for i in cands
                 if (i.get("usage_page") or 0) == parsed["usage_page"]
                 and (i.get("usage") or 0) == parsed["usage"]]
    if cands and parsed.get("interface") is not None:
        same = [i for i in cands if i.get("interface_number") == parsed["interface"]]
        cands = same or cands
    return cands[0] if cands else None


# ---------------- 猜类型 ----------------
_MOUSE_KEYS = ("mouse", "superlight", "pro x", "鼠标", "g pro", "gpx", "mx master")
_KEY_KEYS = ("keyboard", "keychron", "kbd", "键盘", "rainy", "keys")
_HEAD_KEYS = ("headset", "headphone", "earbud", "耳机", "耳麦", "cloud", "飓风",
              "zone ", "g733", "g pro x wireless")


def kind_from(info: dict, name: str) -> str:
    n = (name or "").lower()
    page = info.get("usage_page") or 0
    use = info.get("usage") or 0
    if any(k in n for k in _HEAD_KEYS):
        return HEADSET
    if page == 0x0001 and use == 0x0002:
        return MOUSE
    if page == 0x0001 and use == 0x0006:
        return KEYBOARD
    if any(k in n for k in _KEY_KEYS):
        return KEYBOARD
    if any(k in n for k in _MOUSE_KEYS):
        return MOUSE
    return UNKNOWN


# ---------------- 主流程 ----------------
def _from_device(d: Device, info: dict) -> dict:
    return {
        "ok": True,
        "device": d,
        "rule": None,
        "message": f"已识别：{d.name} · {d.percent_text}%"
                   + (f"（{d.source}）" if d.source else ""),
    }


def recognize(text: str) -> dict:
    parsed = parse_endpoint(text)
    if not parsed:
        return {"ok": False, "message": "没看懂这段内容：里面找不到 046D:C54D 这种「厂商:产品」编号。"}

    info = resolve(parsed)
    if not info:
        vid = parsed["vendor_id"]
        pid = parsed["product_id"]
        return {"ok": False,
                "message": f"这个端点现在不在线（{vid:04X}:{pid:04X}），"
                           "确认接收器还插着、设备没关机，然后重新复制一次。"}

    name = (info.get("product") or "").strip()
    if not name or name == "-":
        name = (info.get("product_string") or "").strip()
    kind = kind_from(info, name)
    debug: list[str] = []

    # 1) 罗技：内置 HID++ 通道（GPW 这类设备的电量只走这里）
    if (info.get("vendor_id") or 0) == LOGITECH_VID:
        devices = hidpp.scan_logitech(debug, force=True)
        for d in devices:
            if d.vid_pid == f"{info['vendor_id']:04X}:{info['product_id']:04X}":
                if d.kind == UNKNOWN and kind != UNKNOWN:
                    d.kind = kind
                return _from_device(d, info)
        return {"ok": False,
                "message": "这条罗技端点没有应答 HID++ 协议。"
                           "请改复制用途写着「★ 电量/协议通道」的那一行；"
                           "若那行也没反应，多半是设备在省电态，动一下鼠标再试。",
                "debug": debug}

    # 2) VGN/ATK：Evision 私有协议
    if (info.get("vendor_id") or 0) == EVISION_VID:
        devices = evision.scan_evision(debug, force=True)
        for d in devices:
            if d.vid_pid == f"{info['vendor_id']:04X}:{info['product_id']:04X}":
                if d.kind == UNKNOWN and kind != UNKNOWN:
                    d.kind = kind
                return _from_device(d, info)

    # 3) 其他品牌：被动监听，找稳定字节
    path = info.get("path")
    if not path:
        return {"ok": False, "message": "端点没有可用路径，无法监听。"}
    result = raw_hid.sniff_candidates(path, 3.0, "")
    candidates = [c for c in (result.get("candidates") or [])
                  if c.get("stable") and c.get("samples", 0) >= 3]
    debug.append(f"[被动监听] 采集 {result.get('total', 0)} 条报文，"
                 f"稳定候选 {len(candidates)} 个")
    if result.get("error"):
        debug.append(f"[被动监听] {result['error']}")
        return {"ok": False,
                "message": f"这个端点读不了：{result['error']}。"
                           "通常是只用来发指令的通道，改复制标 ★ 的那一行再试。",
                "debug": debug}
    if not candidates:
        return {"ok": False,
                "message": "这条通道没有出现可用的电量字节。"
                           "这类设备只在被主动询问时才回报电量，需要厂商指令才能读，"
                           "可以点「导出诊断报告」发回来，我照着补协议。",
                "debug": debug}

    best = candidates[0]
    label = name or f"{info['vendor_id']:04X}:{info['product_id']:04X}"
    rule = {
        "name": label,
        "kind": kind,
        "match": {
            "vendor_id": info.get("vendor_id"),
            "product_id": info.get("product_id"),
            "usage_page": info.get("usage_page"),
            "usage": info.get("usage"),
        },
        "query": "",
        "report_id": best["report_id"],
        "byte": best["byte"],
        "transport": "2.4G 接收器",
        "timeout": 2.0,
    }
    device = Device(
        key=f"rule:{info.get('vendor_id')}:{info.get('product_id')}:{label}",
        name=label,
        kind=kind,
        level=float(best["value"]),
        source="自定义报文规则",
        transport="2.4G 接收器",
        vid_pid=f"{info['vendor_id']:04X}:{info['product_id']:04X}",
    )
    return {"ok": True, "device": device, "rule": rule,
            "message": f"已识别：{label} · {int(best['value'])}%（报文 0x{best['report_id']:02X} "
                       f"第 {best['byte']} 字节，已存成规则）",
            "debug": debug}
