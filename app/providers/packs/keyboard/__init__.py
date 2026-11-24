# -*- coding: utf-8 -*-
"""键盘：按品牌分文件，一个文件管这个品牌在这一类型下的全部型号。

`MODULES` 的顺序就是优先级。3554:FA09 上叠着三家键盘（AULA F99 Pro / 凌豹 K98 /
迈从 G75），HID 层完全同指纹，只能靠会话 ACK 的型号码分流，所以这三家必须按
aula → lingbao → mchose 排，先试的读不到型号会主动让位。

`_compx.py` 是这三家共用的会话协议帧，不是独立链路，不参与扫描。
"""
from providers.packs.keyboard import (
    ajazz, asus, atk, aula, cherry, eweadn, ganss, lingbao, mchose, vgn,
)

MODULES = (
    aula,               # 3554:FA09 F99 Pro / 372E:106C HERO 68 Air
    cherry,             # 046A PIXIU75 块读
    ajazz,              # 3151:4011 黑爵 AK870
    lingbao,            # 3554:FA09 凌豹 K98
    eweadn,             # 0C45:FEFE 前行者 X87
    asus,               # 0B05:1ACE Scope II 96（要跨接口核对配对表）
    mchose,             # 3837 V1 键盘 / K7 / QHW 新代 dongle
    vgn,                # 320F:5088 V98 Pro
    atk,                # 373B VIA 通道
    ganss,              # 05AC:024F GS3104T-Pro / F108 Pro
)
