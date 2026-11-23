# -*- coding: utf-8 -*-
"""独立自检脚本：列出所有 HID 端点，并尝试 HID++ / 系统电量两条通道。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import hid  # noqa: E402

from providers import hidpp, win_pnp  # noqa: E402


def main() -> None:
    rows = []
    for d in hid.enumerate():
        rows.append({
            "vid": d.get("vendor_id"),
            "pid": d.get("product_id"),
            "page": d.get("usage_page"),
            "usage": d.get("usage"),
            "if": d.get("interface_number"),
            "product": (d.get("product_string") or "")[:32],
            "mfr": (d.get("manufacturer_string") or "")[:24],
        })
    rows.sort(key=lambda r: (r["vid"] or 0, r["pid"] or 0, r["if"] or 0))

    print(f"== HID 端点总数: {len(rows)} ==")
    for r in rows:
        print(f"  {r['vid']:04X}:{r['pid']:04X} if={r['if']} page=0x{(r['page'] or 0):04X} "
              f"usage=0x{(r['usage'] or 0):04X}  {r['mfr']} | {r['product']}")

    print("\n== 厂商汇总 ==")
    for (vid, mfr), cnt in Counter((r["vid"], r["mfr"]) for r in rows).most_common():
        print(f"  {vid:04X}  {mfr or '(未知)':24s} {cnt} 个端点")

    print("\n== 通道一：HID++ 探测 ==")
    dbg: list[str] = []
    devs = hidpp.scan_logitech(dbg)
    for line in dbg:
        print("  " + line)
    print(f"  -> 命中 {len(devs)} 个设备")
    for d in devs:
        print(f"     {d.name} | {d.type_label} | {d.level}% | 充电={d.charging} | {d.source}")

    print("\n== 通道二：系统电量属性 ==")
    dbg2: list[str] = []
    devs2 = win_pnp.scan_windows_battery(dbg2)
    for line in dbg2:
        print("  " + line)
    for d in devs2:
        print(f"     {d.name} | {d.type_label} | {d.level}% | {d.source}")


if __name__ == "__main__":
    main()
