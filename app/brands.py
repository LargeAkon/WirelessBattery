# -*- coding: utf-8 -*-
"""这些品牌的 2.4G 接收器实际走哪条电量帧。

品牌名只用来告诉人和诊断窗口「这台该问哪套协议」。
真正读电量的是方案商帧：校验或应答头对不上就丢弃，不按品牌造一个百分比。

没有单独 VID 的贴牌（仁魔、LunaFury、西伯利亚、iKF、WEIKAV、阿斯盾、
ROYUAN、狼途、EXX、ZYNOO、觅声、名龙星球、前行者、CRDRAKO、水月雨、
漫步者 HECATE、LEADJOY 等）插上后仍会走下面两条不看 VID 的通道：

- 页面 ``FF02 / 用法 0002`` 的 Compx 17 字节帧
- HID 描述符里的标准 Battery Strength，以及 Windows 电池属性

对得上才出现在列表里。
"""
from __future__ import annotations

# 特征报告 0x83：中颖 / 万灵 / 兰族 / 卓威 / 迈从 8K 这一支。
FEATURE83 = frozenset({
    0x258A,  # 中颖公版：狼蛛、前行者、部分黑爵、部分多彩
    0x36A7,  # 万灵花兽 WLmouse
    0x373E,  # 兰族 LAMZU Maya X
    0x37B0,  # 兰族 Inca / Paro 一类
    0x33E4,  # G-Wolves
    0x2023,  # 迈从 A5
    0x3837,  # 迈从 A7
    0x5253,  # 迈从 M7
})

# ATK Zero 这一支 Nordic 54。VAXEE 也占用 FF05，所以不能按页面盲发。
NORDIC54 = frozenset({0x373B})

STEELSERIES = frozenset({0x1038})
JBL = frozenset({0x0ECB})
FLYDIGI = frozenset({0x37D7})
# 迈从 G7 是另一条 ``AA 30`` 应答，不走 0x83。
MCHOSE_G7 = frozenset({0xA8A5})

# Nova 7 Gen2 / 2026：内核驱动写明电量是百分比，不是 0–4 档。
ARCTIS_DIRECT = frozenset({
    0x22A1, 0x22A7, 0x22A5, 0x22A9,
    0x227E, 0x2258, 0x229E, 0x22AD,
})

# VID → (诊断标题, 读取路径)
_ROWS: dict[int, tuple[str, str]] = {
    0x046D: ("Logitech 罗技", "HID++ 2.0 / 1.0，含 Bolt 与 LIGHTSPEED"),
    0x03F0: ("HyperX", "Cloud / Pulsefire 只读电量"),
    0x0951: ("HyperX 金士顿", "Cloud II 无线只读电量"),
    0x24AE: ("Rapoo 雷柏", "监听 BB B0；带 FF02 的型号同时走 Compx"),
    0x260D: ("Dareu 达尔优", "Compx 17 字节帧（A950 一类）"),
    0x062A: ("Delux 多彩", "M618 等 MosArt 接收器，有标准电量字段才读"),
    0x3554: (
        "Compx 公版",
        "17 字节电量帧。ATK / VXE / VGN / 达尔优 / Pulsar 派世 / "
        "Attack Shark / 狼蛛键盘 / Ninjutso / 因科特 / Hitscan / "
        "塞洛斯 / Finalmouse / 赴极 等贴牌",
    ),
    0x373B: (
        "Compx 新接收器",
        "旧款仍是 17 字节帧；ATK Zero 走 Nordic 54",
    ),
    0x3710: ("Pulsar 派世", "Compx 17 字节帧（CrazyLight 一类）"),
    0x3770: ("Hitscan", "Compx 17 字节帧"),
    0x320F: ("ATK / VGN / VXE", "Evision，键盘与部分鼠标"),
    0x373E: ("LAMZU 兰族", "特征报告 0x83"),
    0x37B0: ("LAMZU 兰族", "特征报告 0x83"),
    0x36A7: ("WLmouse 万灵花兽", "特征报告 0x83"),
    0x33E4: ("G-Wolves", "特征报告 0x83"),
    0x2023: ("MCHOSE 迈从", "特征报告 0x83"),
    0x3837: ("MCHOSE 迈从", "特征报告 0x83"),
    0x5253: ("MCHOSE 迈从", "特征报告 0x83"),
    0xA8A5: ("MCHOSE 迈从 G7", "输出报告 AA 30"),
    0x3151: ("怒喵 / 黑爵 / 部分 Akko", "状态报告 0x05"),
    0x3057: ("VAXEE", "特征报告 0x0E，5% 一档"),
    0x2DC8: ("8BitDo 八位堂", "输入报告第 14 字节；XInput 模式走手柄四档"),
    0x054C: ("Sony 索尼", "DualSense / DualShock 输入报告"),
    0x0B05: ("ASUS 华硕 ROG / TUF", "指令 12 07 / 12 01"),
    0x1532: ("Razer 雷蛇", "标准电量指令 0x07/0x80"),
    0x1038: ("SteelSeries 赛睿", "Arctis b0、Aerox d2、Rival 3 的 aa"),
    0x0ECB: ("JBL", "Quantum 接收器主动上报 0x08"),
    0x37D7: ("Flydigi 飞智", "GET_INFO，电量在低 4 位"),
    0x04B4: ("Flydigi 飞智 旧款", "多数只暴露 XInput 四档"),
    0x388D: ("Lofree", "自有 FF1C 帧，没有对过的样本就不发送"),
    0x372E: ("IPI", "自有协议，电量字节未确认，不发送猜测帧"),
    0x1D57: ("Attack Shark 旧接收器", "不是 Compx 17 字节帧，对不上就不显示"),
    0x1395: ("EPOS", "有标准电量字段或系统电池才读"),
    0x057E: ("Nintendo 任天堂", "Switch 手柄是 USB / 蓝牙，不当作 2.4G 接收器去写"),
    0x258A: (
        "SINOWEALTH 中颖",
        "特征报告 0x83。狼蛛、前行者、部分黑爵、部分多彩；"
        "固件没做电量字段的型号读不到",
    ),
    0x25A7: ("PixArt / Areson", "Compx 帧，0x09 应答按 10% 一档"),
    0x0C45: (
        "Sonix 松翰公版",
        "西伯利亚、iKF、阿斯盾、前行者、漫步者一类贴牌常见；"
        "有标准电量字段才读得到",
    ),
    0x1EA7: ("Holtek 合泰公版", "有标准电量字段才读得到"),
}


def describe(vid: int | None) -> str | None:
    row = _ROWS.get(vid or 0)
    if row is None:
        return None
    title, path = row
    return f"{title} · {path}"
