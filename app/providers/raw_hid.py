# -*- coding: utf-8 -*-
"""通道三：自定义报文规则（面向私有协议的 2.4G 接收器）。

界面上"嗅探"一次，选中承载电量的字节，即生成一条规则存入配置；
之后每次刷新按规则读取，无需再干预。可用于任何厂商的私有 HID 报文。
"""
from __future__ import annotations

import time

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from model import Device, UNKNOWN
from providers.hidlist import devices as hid_devices


def _hex_to_bytes(text: str) -> bytes:
    cleaned = (text or "").replace(",", " ").replace("0x", " ").split()
    out = bytearray()
    for token in cleaned:
        try:
            out.append(int(token, 16))
        except ValueError:
            continue
    return bytes(out)


def _open(path: bytes):
    dev = hid.device()
    dev.open_path(path)
    dev.set_nonblocking(0)
    return dev


def read_reports(path: bytes, seconds: float = 2.5, query: str = "",
                 max_reports: int = 60) -> list[tuple[int, bytes]]:
    """在指定端点上采集原始报文，返回 [(report_id, payload), ...]。"""
    return _collect(path, seconds, query, max_reports)[0]


def _collect(path: bytes, seconds: float, query: str,
             max_reports: int) -> tuple[list[tuple[int, bytes]], str | None]:
    """采集报文，同时把"为什么一条都没有"带出来。

    有些端点能打开但一读就报错（该 collection 只有输出报告，或厂商驱动
    独占）。原来异常被吞掉、只返回空列表，界面就只能说"没抓到电量"，
    分不清是设备不说话还是这条路根本读不了。
    """
    if hid is None:
        return [], "缺少 hid 库"
    collected: list[tuple[int, bytes]] = []
    try:
        dev = _open(path)
    except Exception as exc:
        return [], f"打不开端点（可能被厂商驱动独占）：{exc}"
    error: str | None = None
    try:
        if query:
            try:
                dev.write(_hex_to_bytes(query))
            except Exception:
                pass
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(collected) < max_reports:
            left = deadline - time.monotonic()
            try:
                data = dev.read(64, max(1, int(left * 1000)))
            except Exception as exc:
                error = f"该端点不接受读取：{exc}"
                break
            if not data:
                continue
            raw = bytes(data)
            rid = raw[0] if raw else 0
            collected.append((rid, raw))
    finally:
        try:
            dev.close()
        except Exception:
            pass
    return collected, error


def _find_path(match: dict) -> bytes | None:
    if hid is None:
        return None
    for info in hid_devices():
        if match.get("vendor_id") is not None and info.get("vendor_id") != match["vendor_id"]:
            continue
        if match.get("product_id") is not None and info.get("product_id") != match["product_id"]:
            continue
        if match.get("usage_page") is not None and info.get("usage_page") != match["usage_page"]:
            continue
        if match.get("usage") is not None and info.get("usage") != match["usage"]:
            continue
        return info.get("path")
    return None


def read_rule(rule: dict) -> tuple[float | None, bool]:
    """按规则读取一次电量。返回 (百分比, 是否充电)。"""
    path = _find_path(rule.get("match") or {})
    if not path:
        return None, False
    reports = read_reports(
        path, seconds=float(rule.get("timeout", 2.0)),
        query=rule.get("query", ""), max_reports=8,
    )
    want_rid = rule.get("report_id")
    byte_index = int(rule.get("byte", 0))
    charge_byte = rule.get("charge_byte")
    charge_mask = int(rule.get("charge_mask", 0))

    for rid, payload in reports:
        if want_rid is not None and rid != want_rid:
            continue
        idx = byte_index + 1  # payload[0] 为 report id
        if idx >= len(payload):
            continue
        value = payload[idx]
        if value == 0xFF:
            continue
        if 0 <= value <= 100:
            charging = False
            if charge_byte is not None and charge_mask:
                ci = int(charge_byte) + 1
                if ci < len(payload):
                    charging = bool(payload[ci] & charge_mask)
            return float(value), charging
    return None, False


def scan_custom(rules: list[dict], debug: list | None = None) -> list[Device]:
    devices: list[Device] = []
    for rule in rules or []:
        name = rule.get("name") or "自定义外设"
        try:
            level, charging = read_rule(rule)
        except Exception as exc:
            if debug is not None:
                debug.append(f"[自定义] {name} 读取异常: {exc}")
            continue
        if debug is not None:
            debug.append(f"[自定义] {name} 电量={level} 充电={charging}")
        if level is None:
            continue
        match = rule.get("match") or {}
        devices.append(Device(
            key=f"rule:{match.get('vendor_id')}:{match.get('product_id')}:{name}",
            name=name,
            kind=rule.get("kind") or UNKNOWN,
            level=level,
            charging=charging,
            source="自定义报文规则",
            transport=rule.get("transport") or "2.4G 接收器",
        ))
    return devices


# ---------------- 嗅探辅助（供诊断界面使用） ----------------
# 标准 usage page/usage 的中文含义。用户看到"0x0001 / 0x0006"根本判断不出
# 该选哪一行 —— 这些编号是 USB HID 规范里的用途分类，不是给人看的。
_USAGE_ROLE = {
    (0x0001, 0x0001): "指针",
    (0x0001, 0x0002): "鼠标",
    (0x0001, 0x0004): "摇杆",
    (0x0001, 0x0005): "游戏手柄",
    (0x0001, 0x0006): "键盘",
    (0x0001, 0x0007): "小键盘",
    (0x0001, 0x0080): "系统控制",
    (0x0002, 0x0001): "仿真设备",
    (0x0006, 0x0001): "扫描仪",
    (0x0007, 0x0001): "传感器",
    (0x0009, 0x0001): "HID 设备",
    (0x000B, 0x0001): "遥控",
    (0x000C, 0x0001): "多媒体键",
    (0x000D, 0x0001): "数字化仪",
    (0x000D, 0x0002): "笔",
}


def _role_of(usage_page: int, usage: int) -> str:
    page = usage_page or 0
    use = usage or 0
    if page >= 0xFF00:
        # 厂商自己定义的页：电量和所有私有指令都走这里，功率最高的嫌疑对象
        return "厂商协议·长报文" if use == 0x0002 else (
            "厂商协议·短报文" if use == 0x0001 else "厂商协议")
    return _USAGE_ROLE.get((page, use), "标准用途")


def describe_endpoints() -> list[dict]:
    if hid is None:
        return []
    out = []
    for info in hid_devices():
        page = info.get("usage_page") or 0
        use = info.get("usage") or 0
        out.append({
            "vendor_id": info.get("vendor_id"),
            "product_id": info.get("product_id"),
            "usage_page": page,
            "usage": use,
            "interface": info.get("interface_number"),
            "product": info.get("product_string") or "",
            "manufacturer": info.get("manufacturer_string") or "",
            "path": info.get("path"),
            "role": _role_of(page, use),
            # 只有罗技那种 0xFF00 长报文口能承载 HID++ 电量；先不写死品牌，
            # 凡 0xFF00 页都算候选，0x0002（长报文）优先。
            "vendor_page": page == 0xFF00 and use in (0x0001, 0x0002),
        })
    def _battery_rank(ep: dict) -> int:
        page = ep.get("usage_page") or 0
        use = ep.get("usage") or 0
        if page == 0xFF1C and use == 0x0092:
            return 0
        if page == 0xFF02 and use == 0x0002:
            return 1
        if page == 0xFF43 and use in (0x0002, 0x0202):
            return 2
        if ep.get("vendor_page") and use == 0x0002:
            return 3
        if ep.get("vendor_page"):
            return 4
        if page >= 0xFF00:
            return 5
        return 9

    out.sort(key=lambda r: (r["vendor_id"] or 0, r["product_id"] or 0,
                            _battery_rank(r),
                            r["usage_page"] or 0, r["usage"] or 0))

    # 有些接收器（如 258A:1007）把同一个 usage 拆成 5 个 collection，
    # 表格里就是 5 行一模一样的记录，人只会更懵。同一 (vid,pid,页,用法,接口)
    # 只留第一行 —— 它们指向同一路数据，嗅探哪个都一样。
    deduped: list[dict] = []
    seen_row: set = set()
    for ep in out:
        row_key = (ep["vendor_id"], ep["product_id"], ep["usage_page"],
                   ep["usage"], ep["interface"])
        if row_key in seen_row:
            continue
        seen_row.add(row_key)
        deduped.append(ep)
    out = deduped

    # 每只接收器只标一条最可能出电量的口：Evision 的 FF1C、Compx 的 FF02，
    # 然后才是罗技长报文。普通鼠标/键盘输入行不标。
    seen: set = set()
    for ep in out:
        ep["recommend"] = False
        key = (ep["vendor_id"], ep["product_id"])
        rank = _battery_rank(ep)
        if rank <= 5 and key not in seen:
            ep["recommend"] = True
            ep["role"] = "★ 电量/协议通道"
            seen.add(key)
    return out


def sniff_candidates(path: bytes, seconds: float = 3.0, query: str = "") -> dict:
    """采集报文并给出"可能是电量"的字节候选。

    返回 {"reports": [(rid, hex)], "candidates": [...], "error": str|None}
    """
    reports, error = _collect(path, seconds, query, 80)
    grouped: dict[int, list[bytes]] = {}
    for rid, payload in reports:
        grouped.setdefault(rid, []).append(payload)

    preview = []
    for rid, payload in reports[:12]:
        preview.append((rid, payload.hex(" ")))

    candidates = []
    for rid, payloads in grouped.items():
        if not payloads:
            continue
        length = min(len(p) for p in payloads)
        for byte_index in range(1, length):
            values = [p[byte_index] for p in payloads]
            in_range = [v for v in values if 1 <= v <= 100]
            if not in_range:
                continue
            stable = len(set(in_range)) == 1
            candidates.append({
                "report_id": rid,
                "byte": byte_index - 1,
                "value": in_range[0],
                "stable": stable,
                "samples": len(values),
                "hex": payloads[0].hex(" "),
            })
    candidates.sort(key=lambda c: (not c["stable"], -c["value"]))
    return {"reports": preview, "candidates": candidates[:40],
            "total": len(reports), "error": error}
