# -*- coding: utf-8 -*-
"""从描述符里读出每个 report ID 的报文长度。

hidapi 的 enumerate 只给 usage page / usage，不给报文长度，而厂商协议的判据
大量依赖"这条集合的输出报文正好 N 字节"。没有长度就只能在同 VID 的所有集合
上盲试，容易把帧写到不该写的接口上。

这里按 HID 规范解析报告描述符（IOCTL_HID_GET_REPORT_DESCRIPTOR，复用
hid_desc.read_descriptor），统计每个 report ID 在 input / output / feature
三类的总字节数 —— 口径与 hidapi 一致：**含 report ID 那一字节**。
"""
from __future__ import annotations

from providers.hid_desc import read_descriptor

_CACHE: dict[bytes, dict[str, dict[int, int]]] = {}
# 拔插过的每个接口都会留下一条 path。正常机器十几条，长期运行会慢慢攒；
# 每条只是几个整数，但没必要无限留着，满了整体清掉重新解析即可。
_CACHE_MAX = 128


def _parse(desc: bytes) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {"in": {}, "out": {}, "feat": {}}
    if not desc:
        return out
    report_id = 0
    size = count = 0
    bits = {"in": 0, "out": 0, "feat": 0}
    i = 0
    n = len(desc)
    while i < n:
        prefix = desc[i]
        if prefix == 0xFE:                      # 长条目：跳过
            length = desc[i + 1] if i + 1 < n else 0
            i += 3 + length
            continue
        size_code = prefix & 0x03
        width = (0, 1, 2, 4)[size_code]
        itype = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        data = desc[i + 1:i + 1 + width]
        i += 1 + width
        value = int.from_bytes(data, "little") if data else 0

        if itype == 1:                          # 全局条目
            if tag == 7:                        # Report Size
                size = value
            elif tag == 8:                      # Report ID：换号即换报文
                if value != report_id:
                    # 换了报文号，位计数必须从头开始。以前这里不清零，
                    # 后续报文号的长度会把前面所有报文的位数累加进来，
                    # 于是 io_lengths 的"最大长度"偏大，靠长度认设备的
                    # 型号（如迈从、ATK）就永远匹配不上。
                    bits = {"in": 0, "out": 0, "feat": 0}
                report_id = value
            elif tag == 9:                      # Report Count
                count = value
            continue
        if itype != 0:                          # 局部条目不影响长度
            continue

        # 主条目：Input / Output / Feature 各自累加位数
        kind = {0x8: "in", 0x9: "out", 0xB: "feat"}.get(tag)
        if kind is None:
            continue
        if count <= 0 or size <= 0:
            continue
        bits[kind] += size * count
        total = 1 + (bits[kind] + 7) // 8       # +1：report ID
        out[kind][report_id] = total
    return out


def reports(path) -> dict[str, dict[int, int]]:
    """该接口的 {in/out/feat: {report_id: 总字节数}}，按 path 缓存。"""
    key = path if isinstance(path, bytes) else str(path).encode("utf-8", "ignore")
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    desc = _descriptor(key)
    parsed = _parse(desc) if desc else {"in": {}, "out": {}, "feat": {}}
    _CACHE[key] = parsed
    return parsed


def _descriptor(path: bytes) -> bytes:
    """取报告描述符。

    优先用 hidapi 自带的 `get_report_descriptor()`：它按设备要求的访问
    权限打开句柄；自己用 CreateFileW + IOCTL 走同一条路会被拒（实测
    Access Denied），所以只留作兜底。
    """
    try:
        import hid

        dev = hid.device()
        dev.open_path(path)
        try:
            desc = dev.get_report_descriptor()
            return bytes(desc or b"")
        finally:
            dev.close()
    except Exception:
        pass
    try:
        return read_descriptor(path)
    except Exception:
        return b""


def has_report(path, kind: str, report_id: int, length: int | None = None) -> bool:
    found = reports(path).get(kind, {}).get(report_id)
    if found is None:
        return False
    return found == length if length is not None else True


def length_of(path, kind: str, report_id: int) -> int | None:
    return reports(path).get(kind, {}).get(report_id)
