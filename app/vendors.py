# -*- coding: utf-8 -*-
"""VID → 无线方案商对照表。

市面上外设品牌几百个，但 2.4G 无线方案就那么几家：一家方案商后面挂着
几十个贴牌品牌（同一个公版方案换个壳就上新品牌）。所以"这是哪家方案"
比"这是哪个品牌"有用得多 —— 适配一家等于覆盖一批。

品牌 VID 在 brands.py。这里只留没有单独品牌条目的芯片和系统设备。
两张表都只做诊断展示，不会因为表里没有某个 VID 就排除设备。
"""
from __future__ import annotations

from brands import describe as describe_brand

VENDORS: dict[int, tuple[str, str]] = {
    0x1B1C: ("Corsair 海盗船", "部分型号走 Compx 帧"),
    0x413C: ("Dell 戴尔", "多为整机外设，不在外设协议范围"),
    0x045E: ("Microsoft 微软", "多为整机外设，不在外设协议范围"),
    0x05AC: ("Apple", "多为整机外设，不在外设协议范围"),
    0x04F2: ("Chicony 群光", "有厂商端点才读得到"),
    0x0BDA: ("Realtek 瑞昱", "有厂商端点才读得到"),
    0x0A12: ("CSR 蓝牙", "本工具不显示蓝牙"),
    0x8087: ("Intel 蓝牙", "本工具不显示蓝牙"),
    0x0A5C: ("Broadcom 博通蓝牙", "本工具不显示蓝牙"),
    0x04CA: ("Lite-On 建兴", "有厂商端点才读得到"),
    0x045B: ("Renesas 瑞萨", "有厂商端点才读得到"),
}


def describe(vid: int | None) -> str:
    branded = describe_brand(vid)
    if branded:
        return branded
    name, path = VENDORS.get(
        vid or 0,
        ("未知厂商", "仍会试芯片组与协议包，对不上就不显示"),
    )
    return f"{name} · {path}"
