# -*- coding: utf-8 -*-
"""耳机：按品牌分文件，一个文件管这个品牌在这一类型下的全部型号。

`MODULES` 的顺序就是优先级。耳机多为被动上报，读不到就下一轮再来，
所以顺序只在"同一接收器被多套协议命中"时才起作用。
"""
from providers.packs.headset import (
    akg, asus, aula, darkrim, hyperx_cf2, mchose, razer, sony,
)

MODULES = (
    hyperx_cf2,         # 03F0:0AC1 Cloud Flight 2，纯被动
    aula,               # 38A6:0030 狼蛛 G9，纯被动
    darkrim,            # 3654:6901 寸渊影弑 SHADOW
    asus,               # 0B05:1AFA ROG 无线耳机
    razer,              # 1532:0555 BlackShark / 1532:056C Kraken V4
    mchose,             # 291D V9 Pro / 3837:6045 X9
    akg,                # 0ECB:20D9 N9 Hybrid，RACE 消息
    sony,               # 054C:0FA8 INZONE H9 II
)
