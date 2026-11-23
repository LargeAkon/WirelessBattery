# -*- coding: utf-8 -*-
"""VID → 无线方案商对照表。

市面上外设品牌几百个，但 2.4G 无线方案就那么几家：一家方案商后面挂着
几十个贴牌品牌（同一个公版方案换个壳就上新品牌）。所以"这是哪家方案"
比"这是哪个品牌"有用得多 —— 适配一家等于覆盖一批。

这张表只做诊断展示（告诉用户 / 开发者这台设备该走哪条路），不参与任何判断，
也不会因为表里没有某个 VID 就排除设备。
"""
from __future__ import annotations

# VID: (方案商, 已知读取路径)
VENDORS: dict[int, tuple[str, str]] = {
    0x046D: ("Logitech 罗技", "HID++ 2.0 / 1.0，含 Bolt"),
    0x320F: ("ATK / VGN / VXE 键盘", "Evision，已支持"),
    0x3554: ("Compx 康派", "17 字节电量帧；ATK / VXE / 雷柏贴牌鼠标常见"),
    0x373B: ("Compx 新接收器", "与 3554 同一套电量帧"),
    0x258A: ("SINOWEALTH 中颖", "特征报告 0x83，部分型号无电量"),
    0x1532: ("Razer 雷蛇", "标准电量指令 0x07/0x80"),
    0x24AE: ("Rapoo 雷柏", "监听 0xBB 电量报告"),
    0x0B05: ("ASUS 华硕 ROG", "指令 12 07"),
    0x36A7: ("WLmouse 万灵", "特征报告 0x83"),
    0x373E: ("LAMZU 兰族", "特征报告 0x83"),
    0x33E4: ("G-Wolves", "特征报告 0x83"),
    0x3057: ("VAXEE", "特征报告 0x0E"),
    0x3151: ("怒喵 / 部分黑爵", "状态报告 0x05"),
    0x2023: ("MCHOSE 迈从", "特征报告 0x83"),
    0x2DC8: ("8BitDo 八位堂", "输入报告第 14 字节"),
    0x054C: ("Sony 索尼", "DualSense / DualShock USB 报告"),
    0x0C45: ("Sonix 松翰公版", "有标准电量字段才读得到"),
    0x1EA7: ("Holtek 合泰公版", "有标准电量字段才读得到"),
    0x25A7: ("PixArt 原相", "有标准电量字段才读得到"),
    0x1B1C: ("Corsair 海盗船", "部分型号走 Compx 帧或系统电池"),
    0x1038: ("SteelSeries 赛睿", "有标准电量字段或系统电池才读得到"),
    0x03F0: ("HP / HyperX", "Cloud 2.4G 耳机只读电量"),
    0x0951: ("HyperX 金士顿", "Cloud II 无线只读电量"),
    0x413C: ("Dell 戴尔", "多为系统电池通道"),
    0x045E: ("Microsoft 微软", "系统电池通道"),
    0x05AC: ("Apple", "系统电池通道"),
    0x04F2: ("Chicony 群光", "有标准电量字段才读得到"),
    0x0BDA: ("Realtek 瑞昱", "有标准电量字段才读得到"),
    0x0A12: ("CSR 蓝牙", "本工具不显示蓝牙"),
    0x8087: ("Intel 蓝牙", "本工具不显示蓝牙"),
    0x0A5C: ("Broadcom 博通蓝牙", "本工具不显示蓝牙"),
    0x04CA: ("Lite-On 建兴", "有标准电量字段才读得到"),
    0x045B: ("Renesas 瑞萨", "有标准电量字段才读得到"),
}


def describe(vid: int | None) -> str:
    name, path = VENDORS.get(vid or 0, ("未知厂商", "待识别"))
    return f"{name} · {path}"
