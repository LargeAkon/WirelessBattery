# -*- coding: utf-8 -*-
"""对全部厂商自定义端点做一次被动嗅探，寻找可能承载电量的字节。"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from providers import raw_hid  # noqa: E402


def main() -> None:
    endpoints = raw_hid.describe_endpoints()
    targets = [e for e in endpoints if (e["usage_page"] or 0) >= 0xFF00]
    print(f"自定义页端点 {len(targets)} 个\n")

    seen_signatures = set()
    for ep in targets:
        sig = (ep["vendor_id"], ep["product_id"], ep["usage_page"], ep["usage"])
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)
        print(f"=== {ep['vendor_id']:04X}:{ep['product_id']:04X} "
              f"page=0x{ep['usage_page']:04X} usage=0x{ep['usage']:04X} "
              f"{ep['product']} ===")
        result = raw_hid.sniff_candidates(ep["path"], seconds=3.0, query="")
        print(f"  报文数: {result['total']}")
        for rid, hx in (result["reports"] or [])[:6]:
            print(f"   rid=0x{rid:02X} {hx}")
        cands = result["candidates"]
        if cands:
            print(f"  候选字节 {len(cands)} 个:")
            for c in cands[:12]:
                print(f"    rid=0x{c['report_id']:02X} byte={c['byte']} "
                      f"值={c['value']} 稳定={c['stable']} 样本={c['samples']}")
        print()


if __name__ == "__main__":
    main()
