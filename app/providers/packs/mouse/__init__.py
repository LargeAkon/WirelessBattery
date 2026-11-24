# -*- coding: utf-8 -*-
"""鼠标：按品牌分文件，一个文件管这个品牌在这一类型下的全部型号。

`MODULES` 的顺序就是优先级 —— 同一只接收器被多条链路命中时，排前面的先读。
被动听（不写设备）的排前面，要发查询帧的排后面。
"""
from providers.packs.mouse import (
    atk, aula, eweadn, hecate, inphic_delux, lingbao, mchose, pulsar, rapoo,
    razer, thunderobot, vgn,
)

MODULES = (
    inphic_delux,       # 1D57:FA65 英菲克 / DELUX，纯被动
    hecate,             # 35BB:D00B HECATE G5M Pro
    rapoo,              # 24AE 雷柏 VT3 二代，纯被动
    aula,               # 38A6:28FD 狼蛛 L9 Ultra
    pulsar,             # 3554 派世 X2 V2
    lingbao,            # 3151:402D 凌豹 M5PRO Max
    thunderobot,        # 369B:0234 雷神 ML903
    eweadn,             # 372E:1026 前行者 S9
    razer,              # 1532 毒蝰系列，90 字节 feature
    mchose,             # 3837 A5 / G3 / 鼠标 V2
    vgn,                # 391D / 3554:FB56 蜻蜓 F1 / F2
    atk,                # 373B 鼠标 17 字节
)
