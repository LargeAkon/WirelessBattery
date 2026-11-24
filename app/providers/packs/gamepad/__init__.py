# -*- coding: utf-8 -*-
"""手柄：按品牌分文件，一个文件管这个品牌在这一类型下的全部型号。

`MODULES` 的顺序就是优先级。手柄的读数普遍要发查询帧，且四档电量
（XInput）不在这里 —— 本工具只收能给出确切百分比的那一类。
"""
from providers.packs.gamepad import betop, gamesir, haute, mojhon

MODULES = (
    gamesir,            # 3537 G7 Pro，心跳触发状态流
    betop,              # 20BC / 20DD 北通 T9、鲲鹏 20/70
    haute,              # 054C:0CE6 适配器形态 Haute42 4DS
    mojhon,             # E2B7:122C 墨将 烈风2 GALE2
)
