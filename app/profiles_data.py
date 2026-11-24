# -*- coding: utf-8 -*-
"""内置厂商协议库（数据）。

协议事实来自各厂商公开协议、社区实测与 Linux 驱动源码，共 57 条 / 28 个品牌组。
偏移一位就是假电量，比不显示更糟，所以这里只做记录，不做推断。

结构：
 known_ids [{"vid","pid","wired_pid"}] 已知接收器 ID
 match {"usage_page","usage","require_pid_hit"} 挑哪条 HID 接口
 request {"transport": write_read | feature_read | feature_write_read,
 "payload_hex", "out_len", "in_len", "report_id", "read_matching"}
 response {"markers":[[offset,byte]], "min_length", "exact_length",
 "status":{"offset","ok_values"},
 "level":{"offset","encoding","min","max","scale","add","mask"},
 "charging":{"offset","nonzero","when_charging","mask"}}
 sampling {"attempts","stable_count","request_timeout_ms","total_timeout_s","pick"}

外置协议放配置目录 `device_profiles/*.json`，同 id 整体覆盖内置，
`enabled: false` 表示移除。诊断页「手动适配」保存的就是这种文件。
"""
from __future__ import annotations

import json

BUILTIN_JSON = r"""{
 "asus-rog-mouse": {
 "known_ids": [
 {
 "pid": "",
 "vid": "0B05",
 "wired_pid": ""
 }
 ],
 "label": "华硕 ROG 鼠标（Keris AimPoint 等直连）",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF01"
 },
 "notes": "来源 control-center（libratbag asus.c 补 0x0712 电量命令，Keris Wireless AimPoint 实机逐命令验证）：FF01 私有协议口 65 字节 00 12 07（report id 0 + GET_BATTERY 0x0712 小端）；回包 00 12 07 00 00 PP …，电量 raw[5]。充电字节恒为 1 不可信（硬件限制），故不出充电态。注意：该口在部分固件上拒绝 overlapped 句柄（control-center 实测需同步 IO），若读不到可试 2.4G/有线另一路。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 12 07",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 7,
 "status": {
 "offset": 1,
 "ok_values": [
 18
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "华硕 ROG"
 },
 "asus-rog-omni-kbd": {
 "known_ids": [
 {
 "pid": "1ACE",
 "vid": "0B05",
 "wired_pid": ""
 }
 ],
 "label": "华硕 ROG Omni 键盘（AZOTH 系）",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF00"
 },
 "notes": "来源实测：Omni 接收器 0B05:1ACE 键盘通道（FF00）64 字节 02 12 01；回包电量 offset 6，offset 9 = 1 充电。设备休眠不回话。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "02 12 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 9,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 14,
 "status": {
 "offset": 0,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "华硕 ROG"
 },
 "asus-rog-omni-mouse": {
 "known_ids": [
 {
 "pid": "1ACE",
 "vid": "0B05",
 "wired_pid": ""
 }
 ],
 "label": "华硕 ROG Omni 鼠标（HARPE/KERIS 系）",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF01"
 },
 "notes": "来源实测：Omni 接收器 0B05:1ACE 鼠标通道（FF01）64 字节 03 12 07；回包电量 offset 5，offset 10 > 0 充电。设备休眠不回话。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "03 12 07",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 10
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 11,
 "status": {
 "offset": 0,
 "ok_values": [
 3
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "华硕 ROG"
 },
 "asus-rog-pelta": {
 "keywords": "ROG DELTA II PELTA 耳机 华硕",
 "known_ids": [
 {
 "pid": "1B84",
 "vid": "0B05",
 "wired_pid": ""
 },
 {
 "pid": "1B82",
 "vid": "0B05",
 "wired_pid": ""
 },
 {
 "pid": "1AFA",
 "vid": "0B05",
 "wired_pid": ""
 },
 {
 "pid": "1D41",
 "vid": "0B05",
 "wired_pid": ""
 }
 ],
 "label": "华硕 ROG 耳机（PELTA / DELTA II 系）",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF00"
 },
 "notes": "来源 实机验证（华硕协议）：OUT CC 12 07，回包同前缀，电量 offset 6。交叉确认（DELTA II 1AFA/1D41、PELTA 1B82/1B84，SpeedNova 一代共用帧）；充电需另发 CC 12 08（单查询 schema 暂不含）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "CC 12 07",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 7,
 "status": {
 "offset": 0,
 "ok_values": [
 204
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "华硕 ROG"
 },
 "asus-rog-speednova": {
 "keywords": "ROG 华硕 SPEEDNOVA 8K Harpe II Ace 龙鳞 2 Ace 鼠标",
 "known_ids": [
 {
 "pid": "1AD0",
 "vid": "0B05",
 "wired_pid": ""
 }
 ],
 "label": "华硕 ROG SPEEDNOVA 8K 鼠标（Harpe II Ace 等）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFF01"
 },
 "notes": "来源 公开资料与社区实测：0B05:1AD0，FF01/0001 口报告 03、64 字节；发 03 12 07 + 61x00；回包 03 12 07 开头，电量[5]、[10]>0 充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "03 12 07",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 10
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 11,
 "status": {
 "offset": 0,
 "ok_values": [
 3
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "华硕 ROG"
 },
 "atk-a87-pro": {
 "id": "atk-a87-pro",
 "keywords": "A87 PRO keyboard 键盘",
 "known_ids": [
 {
 "pid": "111F",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK A87 Pro 键盘",
 "match": {
 "usage": "0x0061",
 "usage_page": "0xFF60"
 },
 "notes": "协议事实来源 公开逆向资料 src/Hardware/AtkA87ProHelper.cs。373B:111F FF60:0061，33B Output/Input；02 96 24 联合校验；0电量且0状态为休眠帧。仅查询，不含设置命令；尚未本地硬件验收。",
 "request": {
 "in_len": 33,
 "out_len": 33,
 "payload_hex": "00 02 96 24",
 "read_matching": true,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "mask": 1,
 "nonzero": true,
 "offset": 5
 },
 "exact_length": 33,
 "level": {
 "offset": 4
 },
 "markers": [
 [
 1,
 2
 ],
 [
 2,
 150
 ],
 [
 3,
 36
 ]
 ],
 "min_length": 33
 },
 "sampling": {
 "attempts": 2,
 "pick": "last",
 "request_timeout_ms": 1200,
 "stable_count": 1,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-a9-air": {
 "known_ids": [
 {
 "pid": "1278",
 "vid": "373B",
 "wired_pid": "1293"
 }
 ],
 "label": "ATK A9 Air 大师+ / CompX 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF02"
 },
 "notes": "来源 实测（CompX/Nordic 家族，与 VXE V3 NK 同协议）：17 字节 08 04 + 14x00 + 49；resp[2]=0 状态，resp[6]=电量，resp[7]=1 充电。设备休眠不回话，动一下鼠标再试。373B:1278。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 2,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-f1-family": {
 "keywords": "ATK F1 Pro Max F1 V3 F1 Ultimate 海王星 鼠标",
 "known_ids": [
 {
 "pid": "101B",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "101A",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "1015",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "1303",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "12A9",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "11D9",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "11E4",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "1085",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK F1 Pro Max / F1 V3 / F1 Ultimate 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-n9v2-ultimate": {
 "keywords": "N9 V2 ULTRA ULTIMATE 海王星 耳机",
 "known_ids": [
 {
 "pid": "1262",
 "vid": "373B",
 "wired_pid": ""
 },
 {
 "pid": "12D6",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK N9V2 ULTIMATE 耳机（海王星）",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF90"
 },
 "notes": "来源 ATK HUB app.asar bolutek 协议逆向 + 实机验证：FF90 口 64 字节 55 65 01（命令 0x65，目标 0x01 耳机）；回包 55 65 PP SS…，电量 offset 2，offset 3 = 2 放电 / 3 充电 / 4 满。必须走 FF90（FF82 拒收），写入用 WriteFile 非 SetOutputReport。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "55 65 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 3,
 "when_charging": 3
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 2,
 "scale": 1.0
 },
 "min_length": 4,
 "status": {
 "offset": 1,
 "ok_values": [
 101
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-v75x": {
 "keywords": "ATK V75X Evision 键盘 有线",
 "known_ids": [
 {
 "pid": "5055",
 "vid": "320F",
 "wired_pid": ""
 }
 ],
 "label": "ATK V75X 键盘（USB 有线）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "来源 HaloBattery 1.17.0（ATK HUB Evision 驱动）：仅收录 320F:5055 有线身份；2.4G 接收器 320F:5088 与 VGN V98 Pro / Rainy75 共用且需产品名分流，当前声明式引擎无法区分，暂不内置。FF1C:0092，32 字节 04 <seq lo> <seq hi> 1A + 28x00；回包 status[3]=1A、电量[8]、state[9] 非零=充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 01 00 1A",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 9
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-vxe-nordic54": {
 "known_ids": [
 {
 "pid": "1216",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK / VXE 无线鼠标 (Nordic 54)",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF05"
 },
 "notes": "来源 社区实测 实测：usage 0xFF05，Report 0x08；回包 resp[1]=0x72、resp[5]=0x07，电量 resp[7]。设备休眠时无应答，动一下鼠标再试。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 7D 72 02 00 01 07 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 7,
 "scale": 1.0
 },
 "min_length": 8,
 "status": {
 "offset": 1,
 "ok_values": [
 114
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "atk-z87-keyboard": {
 "known_ids": [
 {
 "pid": "1012",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK Z87 / ATK 系列键盘",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF1C"
 },
 "notes": "来源 atk-battery-tray 实测：usage 0xFF1C，64 字节 04 11 00 1A，电量 resp[8]；休眠时回显变 04 11 00 FF（resp[3]=0xFF、电量清零），status 校验自动排除休眠帧。同协议适用于 373B:1012 等 ATK 键盘。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 11 00 1A",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 9,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK"
 },
 "aula-f108": {
 "keywords": "狼蛛 AULA F108 Pro 键盘",
 "known_ids": [
 {
 "pid": "024F",
 "vid": "05AC",
 "wired_pid": ""
 }
 ],
 "label": "狼蛛 F108 Pro 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0061",
 "usage_page": "0xFF60"
 },
 "notes": "05AC:024F 同指纹（高斯/狼蛛同硅方案），33 字节 00 20 01…21 查询；回包电量 offset 4。品牌按产品名区分，协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 20 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 21",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 4,
 "scale": 1.0
 },
 "min_length": 5,
 "status": {
 "offset": 1,
 "ok_values": [
 32
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "狼蛛 AULA"
 },
 "aula-f99": {
 "keywords": "AULA F99 Pro 狼蛛 F99 键盘",
 "known_ids": [
 {
 "pid": "FA09",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "AULA F99 Pro 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "model_code": 344,
 "notes": "同族接收器共用帧：回包 13 4A 01 00 02…，电量 offset 5、offset 6=16 充电；会话 ACK 型号码分流（K98=0x0212、F99=0x0158），读协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 6,
 "when_charging": 16
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 20,
 "status": {
 "offset": 4,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "狼蛛 AULA"
 },
 "beitong-kp40d": {
 "keywords": "北通 BEITONG KP40D 手柄 接收器",
 "known_ids": [
 {
 "pid": "515C",
 "vid": "20BC",
 "wired_pid": ""
 }
 ],
 "label": "北通 BEITONG KP40D 手柄（2.4G 接收器）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0003",
 "usage_page": "0x00FF"
 },
 "notes": "来源 HaloBattery 1.17.0（iControl USBPcap）：20BC:515C，00FF/0003 厂商集合；64 字节 02 15 + 62x00；回包 02 15 开头，电量[2]，[4]=0x51 充电 / 0x50 放电（手柄估算值）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "02 15",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 4,
 "when_charging": 81
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 2,
 "scale": 1.0
 },
 "min_length": 5,
 "status": {
 "offset": 0,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "北通 BEITONG"
 },
 "cherry-mx2-pro": {
 "known_ids": [
 {
 "pid": "01E0",
 "vid": "046A",
 "wired_pid": ""
 },
 {
 "pid": "01DE",
 "vid": "046A",
 "wired_pid": ""
 }
 ],
 "label": "CHERRY MX 2.0S WL Pro 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "来源 公开实测资料（用户对照，差 3-4 个百分点）：FF1C/0092 口 64 字节 04 20 00 1A 06 + 59 零；回包 byte8=电量 1-100、byte9=0/1 充电。046A:01E0=Dongle、046A:01DE=键盘本体（MI_01）。BLE 0687:01DE 走系统蓝牙电量。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 20 00 1A 06",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 9,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "CHERRY"
 },
 "compx-ff02-17b": {
 "keywords": "ATK VXE 其他 未列型号",
 "known_ids": [
 {
 "pid": "",
 "vid": "373B",
 "wired_pid": ""
 }
 ],
 "label": "ATK / VXE 其他鼠标（自动识别）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "ATK / VXE"
 },
 "dareu-a950-air": {
 "keywords": "DAREU 达尔优 A950",
 "known_ids": [
 {
 "pid": "1175",
 "vid": "260D",
 "wired_pid": ""
 }
 ],
 "label": "达尔优 A950 AIR V2 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "notes": "来源 DAREU Driver 1.5.7 逆向 + 实机：17 字节 08 04 + 14x00 + 49（校验和 sum<55?85-sum，0x49 即此查询的值，CompX 同族帧）；回包 08 04 00 00 00 02 PP CS…，status offset5=2，电量 offset 6，offset 7 = 1 充电 / 2 满。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 7,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 5,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "达尔优 DAREU"
 },
 "darkrim-shadow": {
 "keywords": "影弑 DARKRIM 耳机",
 "known_ids": [
 {
 "pid": "6901",
 "vid": "3654",
 "wired_pid": ""
 }
 ],
 "label": "寸渊影弑 DARKRIM SHADOW 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "来源 社区实测（真机逐字节 + CRC-16/CCITT 校准）：FF02/0002 口 65 字节 00 FE 00 10 00 02 00 00 03 00 09 01 00 E2 3C（GetBasicInfo TLV09，CRC16 大端；写入须写满 65 字节）；回包 FE 00 11…01 01 LL，子类型=1（电量），载荷字节 bit7=充电、低 7 位=百分比。3654:6901（杰理方案，MI_03 口应答）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 FE 00 10 00 02 00 00 03 00 09 01 00 E2 3C",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "mask": 128,
 "nonzero": true,
 "offset": 12
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "mask": 127,
 "max": 100,
 "min": 0,
 "offset": 12,
 "scale": 1.0
 },
 "min_length": 15,
 "status": {
 "offset": 10,
 "ok_values": [
 1
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "寸渊影弑 DARKRIM"
 },
 "delux-gh8k": {
 "keywords": "DELUX 多彩 GH8K M900 Ultra 鼠标 接收器",
 "known_ids": [
 {
 "pid": "FB26",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "多彩 DELUX GH8K / M900 Ultra 2.4G 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "来源 公开实测资料（贡献者 GH8K 90%、用户复验 85%）：3554:FB26 / FF02:0002，双向单一报告 08、17 字节；发 08 04 + 14x00 + 49，回包 status[2]=0、电量[6]；充电位未证实，不显示充电态。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 17,
 "status": {
 "offset": 2,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "多彩 DELUX"
 },
 "eweadn-s9pro": {
 "known_ids": [
 {
 "pid": "1026",
 "vid": "372E",
 "wired_pid": ""
 }
 ],
 "label": "前行者 EWEADN S9 PRO 8K 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFF00"
 },
 "notes": "来源 公开实测资料 + 社区实测（E-HUB 逆向）：FF00/0001 口 feature 64 字节 03 20 50 00 00 4F 81 + 零（SetFeature 后约 100ms GetFeature 03）；回包 03 50 00 0B…LL…A5 5A，字节 6 bit7=充电、低 7 位=电量。372E:1026。",
 "request": {
 "in_len": 64,
 "out_len": null,
 "payload_hex": "03 20 50 00 00 4F 81",
 "report_id": 3,
 "transport": "feature_write_read"
 },
 "response": {
 "charging": {
 "mask": 128,
 "nonzero": true,
 "offset": 6
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "mask": 127,
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 7,
 "status": {
 "offset": 1,
 "ok_values": [
 80
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "前行者 EWEADN"
 },
 "ganss-gs3104": {
 "keywords": "高斯 GANSS GS3104T Pro 键盘",
 "known_ids": [
 {
 "pid": "024F",
 "vid": "05AC",
 "wired_pid": ""
 }
 ],
 "label": "高斯 GS3104T-Pro 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0061",
 "usage_page": "0xFF60"
 },
 "notes": "05AC:024F 同指纹（高斯/狼蛛同硅方案），33 字节 00 20 01…21 查询；回包电量 offset 4。品牌按产品名区分，协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 20 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 21",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 4,
 "scale": 1.0
 },
 "min_length": 5,
 "status": {
 "offset": 1,
 "ok_values": [
 32
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "高斯 GANSS"
 },
 "hecate-g3m": {
 "keywords": "HECATE 漫步者 G3M Pro 鼠标",
 "known_ids": [
 {
 "pid": "706E",
 "vid": "320F",
 "wired_pid": ""
 }
 ],
 "label": "HECATE G3M Pro 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "FF1C/0092 口 64 字节 04 00 00 1A 06；回包 [3]=0x1A、[8]=电量、[9]=0/1 充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 00 00 1A 06",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 9,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HECATE 漫步者"
 },
 "hecate-g5m": {
 "keywords": "漫步者 HECATE G5M",
 "known_ids": [
 {
 "pid": "D00B",
 "vid": "35BB",
 "wired_pid": ""
 }
 ],
 "label": "HECATE G5M Pro 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "来源 HECATE Connect 二进制命令表 + 真机 5/5：FF1C/0092 口 64 字节 04 00 00 1A + 零（0x1A=状态/电量命令）；回包 04 00 00 1A 00 00 00 00 LL CC…，[3]=0x1A 帧标志、[8]=电量、[9]=0 放电/1 充电/2 满。35BB:D00B。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 00 00 1A",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 9,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HECATE 漫步者"
 },
 "hitscan-hyperlight": {
 "keywords": "Hitscan Hyperlight 鼠标",
 "known_ids": [
 {
 "pid": "0200",
 "vid": "3770",
 "wired_pid": ""
 },
 {
 "pid": "0100",
 "vid": "3770",
 "wired_pid": ""
 }
 ],
 "label": "Hitscan Hyperlight 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "Hitscan"
 },
 "hyperx-alpha2": {
 "known_ids": [
 {
 "pid": "08BE",
 "vid": "03F0",
 "wired_pid": ""
 }
 ],
 "label": "HyperX Cloud Alpha 2 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0xFF00",
 "usage_page": "0xFF13"
 },
 "notes": "来源 公开实测资料（NGENUITY USBPcap #26 双电量对照）：FF13/FF00 口 64 字节 50 02；回包 51 02…，电量 offset 2。充电=offset 6 bit7（位域，schema 无掩码故暂不出充电态）。勿用 61 02 帧（非电量）。03F0:08BE 控制半体（0ABE 是纯音频）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "50 02",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 2,
 "scale": 1.0
 },
 "min_length": 3,
 "status": {
 "offset": 0,
 "ok_values": [
 81
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HyperX"
 },
 "hyperx-cloud-alpha-wireless": {
 "known_ids": [
 {
 "pid": "098D",
 "vid": "03F0",
 "wired_pid": ""
 }
 ],
 "label": "HyperX Cloud Alpha Wireless 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0202",
 "usage_page": "0xFF43"
 },
 "notes": "03F0:098D，FF43/0202口，21 BB 0B查询。3.2.0依据公开驱动 hyperx_calphaw.c与公开逆向资料 Devices/CloudAlphaWirelessDevice.cs交叉纠正：电量为回包offset3，不是0x0B命令值对应的offset11。充电必须独立21 BB 0C查询，本单步profile不推断充电；尚未本地硬件验收。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "21 BB 0B",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": null
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 3,
 "scale": 1.0
 },
 "min_length": 4,
 "status": {
 "offset": 2,
 "ok_values": [
 11
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HyperX"
 },
 "hyperx-cloud-iii-s-02cc": {
 "id": "hyperx-cloud-iii-s-02cc",
 "keywords": "Cloud III S 02CC 耳机",
 "known_ids": [
 {
 "pid": "02CC",
 "vid": "03F0",
 "wired_pid": ""
 }
 ],
 "label": "HyperX Cloud III S (Receiver 02CC)",
 "match": {
 "usage": "0x0001",
 "usage_page": "0x01C0"
 },
 "notes": "协议事实来源 公开逆向资料 Devices/Cloud3SAlternateReceiverDevice.cs。精确03F0:02CC、01C0:0001；仅查询selector06电量。充电selector48未接入；未推断其他接收器变体。尚未本地硬件验收。",
 "request": {
 "payload_hex": "0C 02 03 01 00 06",
 "read_matching": true,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": null
 },
 "level": {
 "offset": 6
 },
 "markers": [
 [
 0,
 12
 ],
 [
 1,
 2
 ],
 [
 2,
 3
 ],
 [
 5,
 6
 ]
 ],
 "min_length": 7
 },
 "sampling": {
 "attempts": 2,
 "pick": "last",
 "request_timeout_ms": 1200,
 "stable_count": 1,
 "total_timeout_s": 4.5
 },
 "vendor": "HyperX"
 },
 "hyperx-cloud2-wireless": {
 "known_ids": [
 {
 "pid": "0696",
 "vid": "03F0",
 "wired_pid": ""
 },
 {
 "pid": "018B",
 "vid": "03F0",
 "wired_pid": ""
 }
 ],
 "label": "HyperX Cloud II Wireless 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0303",
 "usage_page": "0xFF90"
 },
 "notes": "来源 公开实测资料（公开驱动同源）：FF90/0303 口 52 字节 06 FF BB 02（cmd 02=电量）；回包 06 FF BB 02…，电量 offset 7。充电需另发 cmd 03（单查询 schema 不含）。0x0696 旧款 / 0x018B 新款。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "06 FF BB 02",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 7,
 "scale": 1.0
 },
 "min_length": 8,
 "status": {
 "offset": 3,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HyperX"
 },
 "hyperx-cloud3-wireless": {
 "known_ids": [
 {
 "pid": "05B7",
 "vid": "03F0",
 "wired_pid": ""
 },
 {
 "pid": "0C9D",
 "vid": "03F0",
 "wired_pid": ""
 },
 {
 "pid": "0FCC",
 "vid": "03F0",
 "wired_pid": ""
 },
 {
 "pid": "0995",
 "vid": "03F0",
 "wired_pid": ""
 },
 {
 "pid": "0795",
 "vid": "03F0",
 "wired_pid": ""
 }
 ],
 "label": "HyperX Cloud III / II Core Wireless 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFF13"
 },
 "notes": "来源 公开实测资料（NGENUITY USBPcap 交叉验证）：FF13/0001 口 62 字节 66 89（cmd 089=电量）；回包 66 89 或 66 0D，电量 offset 4（[2]/[3] 全零为无读数）。充电需另发 66 8A。05B7/0C9D/0FCC=Cloud III，0995/0795=Cloud II Core。部分接收器只收 Feature 报文（write 报错 1 时读不到）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "66 89",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 4,
 "scale": 1.0
 },
 "min_length": 5,
 "status": {
 "offset": 1,
 "ok_values": [
 137,
 13
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "HyperX"
 },
 "imecoo-p1": {
 "known_ids": [
 {
 "pid": "FB34",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "IMECOO P1 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF02"
 },
 "notes": "来源实测（CompX 家族同帧）：17 字节 08 04 + 14x00 + 49；resp[2]=0 状态，resp[6]=电量，resp[7]=1 充电。WriteFile 可用。3554:FB34。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 2,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "IMECOO"
 },
 "leobog-hi75c": {
 "keywords": "LEOBOG 凌咖 Hi75c HI98PRO 键盘",
 "known_ids": [
 {
 "pid": "FA09",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "LEOBOG Hi75c Pro / HI98PRO 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "notes": "同族接收器共用帧：回包 13 4A 01 00 02…，电量 offset 5、offset 6=16 充电；会话 ACK 型号码分流（K98=0x0212、F99=0x0158），读协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 6,
 "when_charging": 16
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 20,
 "status": {
 "offset": 4,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "LEOBOG"
 },
 "lingbao-k98": {
 "keywords": "凌豹 K98 LINGBAO K98 键盘",
 "known_ids": [
 {
 "pid": "FA09",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "凌豹 K98 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "model_code": 530,
 "notes": "同族接收器共用帧：回包 13 4A 01 00 02…，电量 offset 5、offset 6=16 充电；会话 ACK 型号码分流（K98=0x0212、F99=0x0158），读协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 6,
 "when_charging": 16
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 20,
 "status": {
 "offset": 4,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "凌豹 Lingbao"
 },
 "lingbao-m1pro": {
 "known_ids": [
 {
 "pid": "052F",
 "vid": "088D",
 "wired_pid": ""
 }
 ],
 "label": "凌豹 M1 Pro 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFF00"
 },
 "notes": "来源 公开实测资料（两条 65% 帧）：FF00/0001 口 Feature 报告 0x0F（33 字节），单次 GetFeature；byte18=电量 1-100、byte19=0。088D:052F（产品名 Wireless-Receiver，MI_01）。",
 "request": {
 "in_len": 33,
 "out_len": null,
 "payload_hex": "0F",
 "report_id": 15,
 "transport": "feature_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 18,
 "scale": 1.0
 },
 "min_length": 19,
 "status": {
 "offset": 19,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "凌豹 Lingbao"
 },
 "lingbao-m5pro": {
 "keywords": "LINGBAO M5PRO 凌豹",
 "known_ids": [
 {
 "pid": "402D",
 "vid": "3151",
 "wired_pid": ""
 }
 ],
 "label": "凌豹 M5PRO Max 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFFFF"
 },
 "notes": "来源 官方驱动抓包（命令是 F7 非 0x83）：FFFF/0002 口 feature 65 字节 00 F7 00…（SetFeature→GetFeature，无校验和）；回包 [2]=0 成功、[3]=电量、[5]=1 充电。3151:402D（MI_02；有线 4026 只回显不认）。",
 "request": {
 "in_len": 65,
 "out_len": null,
 "payload_hex": "00 F7",
 "report_id": 0,
 "transport": "feature_write_read"
 },
 "response": {
 "charging": {
 "offset": 5,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 3,
 "scale": 1.0
 },
 "min_length": 6,
 "status": {
 "offset": 4,
 "ok_values": [
 1
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "凌豹 Lingbao"
 },
 "mchose-a7-v3": {
 "keywords": "K7 V2 Ultra+ A7 V3 迈丛",
 "known_ids": [
 {
 "pid": "1018",
 "vid": "3837",
 "wired_pid": ""
 },
 {
 "pid": "1014",
 "vid": "3837",
 "wired_pid": ""
 }
 ],
 "label": "迈丛 A7 V3 Pro / Ultra+ 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFF01"
 },
 "notes": "来源 公开逆向资料（#535 实机 84%）：FF01/0001 口 64 字节 4D 01 01 00 00 09 00 00 08（cmd 0x0900 只读电源查询，带 XOR）；回包 4D 01 …，cmd 回显 [4:6]=00 09，data@8：VID 3837、link 非零、offset 19=充电非零、offset 20=电量 0-100。3837:1018/1014。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "4D 01 01 00 00 09 00 00 08",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 19
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 20,
 "scale": 1.0
 },
 "min_length": 21,
 "status": {
 "offset": 5,
 "ok_values": [
 9
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "迈丛 MCHOSE"
 },
 "mchose-g7": {
 "keywords": "MCHOSE 迈丛 G7 YJX 鼠标",
 "known_ids": [
 {
 "pid": "2255",
 "vid": "A8A5",
 "wired_pid": ""
 }
 ],
 "label": "迈丛 MCHOSE G7 鼠标（YJX-CHIP）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0010",
 "usage_page": "0xFF01"
 },
 "notes": "来源 公开实测资料（实机 46%）：A8A5:2255 / FF01:0010；65 字节 00 55 30 A5 0B 2E 01 01 01 + 零；回包 AA 30 开头，电量[8]、[9] 非零=充电。精确 PID 优先于 TAIDU 的 A8A5 通配，避免把 G7 认成钛度。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 55 30 A5 0B 2E 01 01 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 9
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 0,
 "ok_values": [
 170
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "迈丛 MCHOSE"
 },
 "mchose-kb": {
 "keywords": "迈丛 G75 MCHOSE G75 Z75S K99 GX87 键盘",
 "known_ids": [
 {
 "pid": "FA09",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "01BB",
 "vid": "258A",
 "wired_pid": ""
 }
 ],
 "label": "迈丛 G75 Pro / Z75S / K99 / GX87 / G75 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "notes": "同族接收器共用帧：回包 13 4A 01 00 02…，电量 offset 5、offset 6=16 充电；会话 ACK 型号码分流（K98=0x0212、F99=0x0158），读协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 6,
 "when_charging": 16
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 20,
 "status": {
 "offset": 4,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "迈丛 MCHOSE"
 },
 "mchose-v9-headset": {
 "keywords": "V9 PRO X9 迈丛 MCHOSE",
 "known_ids": [
 {
 "pid": "600A",
 "vid": "3837",
 "wired_pid": ""
 },
 {
 "pid": "385D",
 "vid": "291D",
 "wired_pid": ""
 }
 ],
 "label": "迈丛 V9 Turbo+ 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF90"
 },
 "notes": "来源实机抓包：FF90 口 64 字节 55 65 01（与 ATK N9V2 同帧）；回包 55 65 PP SS…，电量 offset 2，offset 3 = 2 放电 / 3 充电 / 4 满。伴生 3837:6008 灯效口不用管。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "55 65 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 3,
 "when_charging": 3
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 2,
 "scale": 1.0
 },
 "min_length": 4,
 "status": {
 "offset": 1,
 "ok_values": [
 101
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "迈丛 MCHOSE"
 },
 "moondrop-gm01": {
 "known_ids": [
 {
 "pid": "0133",
 "vid": "35D8",
 "wired_pid": ""
 }
 ],
 "label": "水月雨 GM01 Pro 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "来源 公开实测资料（用户实机 50%）：FF02/0002 口报告 0x4B，发 4B 80 27 00 + 补零；回包索引 8 非零、索引 9=电量 0-100。35D8:0133。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "4B 80 27 00",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 9,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 0,
 "ok_values": [
 75
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "水月雨 MOONDROP"
 },
 "pulsar-x2": {
 "keywords": "Pulsar 派世 X2 V2 Mini CrazyLight Link 8K 鼠标",
 "known_ids": [
 {
 "pid": "F508",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "F507",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "5406",
 "vid": "3710",
 "wired_pid": ""
 },
 {
 "pid": "3414",
 "vid": "3710",
 "wired_pid": ""
 },
 {
 "pid": "5501",
 "vid": "3710",
 "wired_pid": ""
 }
 ],
 "label": "Pulsar X2 系 / Link 8K 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "Pulsar 派世"
 },
 "rainy75-keyboard": {
 "keywords": "Rainy 75 WOB 键盘",
 "known_ids": [
 {
 "pid": "5088",
 "vid": "320F",
 "wired_pid": ""
 }
 ],
 "label": "Rainy 75 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "来源 网页驱动逆向：320F:5088、FF1C:0092、Report ID 04；查询帧 04 20 00 1A 06，回包 [3]=1A、[8]=电量、[9]=充电状态。与 VGN V98 Pro 共用 VID/PID，添加时需由用户按型号选择。该协议源于网页驱动逆向；尚未实机验证。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 20 00 1A 06",
 "read_matching": true,
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 9
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "last",
 "request_timeout_ms": 1200,
 "stable_count": 1,
 "total_timeout_s": 4.5
 },
 "vendor": "WOB / Rainy75"
 },
 "scyrox-8k": {
 "keywords": "Scyrox 8K 接收器 鼠标",
 "known_ids": [
 {
 "pid": "F517",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "Scyrox 8K 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "Scyrox"
 },
 "taidu-tsg809": {
 "keywords": "VGN 蜻蜓 Dragonfly3 SE 钛度 TAIDU",
 "known_ids": [
 {
 "pid": "",
 "vid": "A8A5",
 "wired_pid": ""
 },
 {
 "pid": "",
 "vid": "A8A4",
 "wired_pid": ""
 },
 {
 "pid": "",
 "vid": "3A37",
 "wired_pid": ""
 }
 ],
 "label": "钛度 TSG809 / HJSDZHI S1-V2 鼠标（YJX-CHIP）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x10",
 "usage_page": "0xFF01"
 },
 "notes": "来源 官方 WebHID 驱动逆向 + 实机验证：65 字节 00 55 30 A5 0B 2E 01 01 01；回包 00 AA 30…，电量 offset 9，offset 10 = 1 充电。官方驱动同时接受 A8A5/A8A4/3A37 三族 VID，FF01/0x10 集合。取代早期未验证的 F0 ED 01 稿。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 55 30 A5 0B 2E 01 01 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 10,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 9,
 "scale": 1.0
 },
 "min_length": 11,
 "status": {
 "offset": 1,
 "ok_values": [
 170
 ]
 }
 },
 "vendor": "钛度 TAIDU"
 },
 "vaxee-3057": {
 "known_ids": [
 {
 "pid": "1001",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1002",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "0005",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "2001",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1003",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1004",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1005",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1006",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1007",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1008",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1009",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1010",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1011",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1012",
 "vid": "3057",
 "wired_pid": ""
 },
 {
 "pid": "1013",
 "vid": "3057",
 "wired_pid": ""
 }
 ],
 "label": "VAXEE / ZYGEN 无线鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x01",
 "usage_page": "0xFF05"
 },
 "notes": "来源 社区实测（VAXEE）：Report 0x0E，命令 0x0B 读电量，回包 offset5 = 0..20 档（×5 = 百分比）。充电需另一命令 0x10，本协议未含。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "0E A5 0B 01 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 20,
 "min": 0,
 "offset": 5,
 "scale": 5.0
 },
 "min_length": 6,
 "status": {
 "offset": 2,
 "ok_values": [
 11
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VAXEE"
 },
 "vgn-beiying-kb": {
 "keywords": "VGN 北影 beiying 键盘",
 "known_ids": [
 {
 "pid": "024F",
 "vid": "258A",
 "wired_pid": ""
 },
 {
 "pid": "027F",
 "vid": "258A",
 "wired_pid": ""
 },
 {
 "pid": "027B",
 "vid": "258A",
 "wired_pid": ""
 },
 {
 "pid": "2A01",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "2A02",
 "vid": "391D",
 "wired_pid": ""
 }
 ],
 "label": "VGN 北影 2.4G 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x02",
 "usage_page": "0xFF02"
 },
 "notes": "同族接收器共用帧：回包 13 4A 01 00 02…，电量 offset 5、offset 6=16 充电；会话 ACK 型号码分流（K98=0x0212、F99=0x0158），读协议相同。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 6,
 "when_charging": 16
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 5,
 "scale": 1.0
 },
 "min_length": 20,
 "status": {
 "offset": 4,
 "ok_values": [
 2
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-dragonfly3": {
 "keywords": "VGN 蜻蜓 Dragonfly3 SE 鼠标",
 "known_ids": [
 {
 "pid": "1A01",
 "vid": "391D",
 "wired_pid": ""
 }
 ],
 "label": "VGN 蜻蜓 Dragonfly3 SE 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x10",
 "usage_page": "0xFF01"
 },
 "notes": "与钛度同 YJX 帧族：00 55 30 A5 0B 2E 01 01 01；回包电量 offset 9、offset 10=1 充电。391D:1A01。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 55 30 A5 0B 2E 01 01 01",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 10,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 9,
 "scale": 1.0
 },
 "min_length": 11,
 "status": {
 "offset": 1,
 "ok_values": [
 170
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-f1-kc2": {
 "known_ids": [
 {
 "pid": "1A23",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1026",
 "vid": "391D",
 "wired_pid": ""
 }
 ],
 "label": "VGN 蜻蜓 F1 V5 Turbo+ 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0001",
 "usage_page": "0xFFC1"
 },
 "notes": "来源 VGN 网页驱动 kc2 控制器 + 真机：FFC1/0001 口 64 字节 B3 06 + 零（report 0xB3，0xB5 备用）；回包 B4 06…，配置帧载荷[19]（Windows raw[20]）bit0-6=电量、bit7=充电。391D:1A23（2.4G）/391D:1026（有线，充电时换 PID 两码都认）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "B3 06",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "mask": 128,
 "nonzero": true,
 "offset": 20
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "mask": 127,
 "max": 100,
 "min": 0,
 "offset": 20,
 "scale": 1.0
 },
 "min_length": 21,
 "status": {
 "offset": 1,
 "ok_values": [
 6
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-f1-moba-f503": {
 "keywords": "VGN 蜻蜓 F1 Moba F503 Dragonfly 鼠标",
 "known_ids": [
 {
 "pid": "F503",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "VGN 蜻蜓 F1 Moba F503 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "来源 公开实测资料（用户完整回复 95%）+ CompX 同族帧：3554:F503 / FF02:0002，17 字节 08 04 + 14x00 + 49；回包电量 offset 6、offset 7 非零=充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-f1-pro": {
 "keywords": "VGN 蜻蜓 F1 Pro Dragonfly 鼠标",
 "known_ids": [
 {
 "pid": "F505",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "VGN 蜻蜓 F1 Pro 鼠标（4K 接收器）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-f2-compx": {
 "keywords": "VGN 蜻蜓 F2 大师 Dragonfly 鼠标",
 "known_ids": [
 {
 "pid": "FB56",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "FB57",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "VGN 蜻蜓 F2 大师+ 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-ryms": {
 "keywords": "VGN 蜻蜓 Dragonfly ryMs Y2 F1 F2 3 Pro Max Ultra 接收器 鼠标",
 "known_ids": [
 {
 "pid": "1A04",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1A08",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1A13",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1A25",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1A2B",
 "vid": "391D",
 "wired_pid": ""
 },
 {
 "pid": "1A41",
 "vid": "391D",
 "wired_pid": ""
 }
 ],
 "label": "VGN ryMs 2.4G 接收器（蜻蜓 3 Pro Max / Y2 V2 Pro Max / F1 V2 Pro Max / 3 Ultra / F1 V5 Ultra / F2 V2 Ultra）",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFFFF"
 },
 "notes": "来源 公开实测资料（VGN HUB ryMs 驱动）：391D:1A04/1A08/1A13/1A25/1A2B/1A41，FFFF/0002 口无编号 Feature 65 字节；发 00 F7 + 6x00 + 校验 08，回包 [3]=电量、[5]=1 休眠；充电未知。1A04 贡献者实测 92%/91%。",
 "request": {
 "in_len": 65,
 "out_len": null,
 "payload_hex": "00 F7 00 00 00 00 00 00 08",
 "report_id": 0,
 "transport": "feature_write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 3,
 "scale": 1.0
 },
 "min_length": 6,
 "status": {
 "offset": 1,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vgn-v98-kb": {
 "keywords": "VGN V98 Pro 键盘",
 "known_ids": [
 {
 "pid": "5088",
 "vid": "320F",
 "wired_pid": ""
 }
 ],
 "label": "VGN V98 Pro 键盘",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0092",
 "usage_page": "0xFF1C"
 },
 "notes": "FF1C/0092 口 64 字节 04 00 00 1A 06；回包 [3]=0x1A、[8]=电量、[9]=0/1 充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "04 00 00 1A 06",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "offset": 9,
 "when_charging": 1
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 8,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 3,
 "ok_values": [
 26
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VGN"
 },
 "vxe-r1-family": {
 "keywords": "VXE R1 Pro Max R1 SE R1 SE+ 鼠标",
 "known_ids": [
 {
 "pid": "F58A",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "F58C",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "F58E",
 "vid": "3554",
 "wired_pid": ""
 },
 {
 "pid": "F58F",
 "vid": "3554",
 "wired_pid": ""
 }
 ],
 "label": "VXE R1 Pro Max / R1 SE 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": "0x0002",
 "usage_page": "0xFF02"
 },
 "notes": "CompX 17 字节 08 04…49（校验 0x55-sum）；回包电量 offset 6、offset 7 非零=充电、8..9 毫伏。373B 表外型号自动命中（精确 PID 条目优先）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 10,
 "status": {
 "offset": 1,
 "ok_values": [
 4
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VXE"
 },
 "vxe-v3-nk": {
 "keywords": "VXE V3 蜻蜓 V3 Dragonfly R1 Nearlink 星闪 NANO 鼠标",
 "known_ids": [
 {
 "pid": "10C9",
 "vid": "373B",
 "wired_pid": "10C7"
 }
 ],
 "label": "VXE V3 NK / R1 Nearlink 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF02"
 },
 "notes": "接收器 373B:10C9；17 字节报文应答，resp[6]=电量，resp[7]!=0 为有线/充电。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 7
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 7,
 "status": {
 "offset": 2,
 "ok_values": [
 0
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "VXE"
 },
 "x7-crociris": {
 "known_ids": [
 {
 "pid": "AA20",
 "vid": "36F9",
 "wired_pid": ""
 }
 ],
 "label": "CROCIRIS X7 Receiver 8K 鼠标",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF0A"
 },
 "notes": "来源 Crociris Hub KM WebHID 逆向：65 字节 00 AA 12 00 00（命令 0x12 查电量）；回包 00 55 12 00 00 CC LL…，status offset1=0x55，offset 5 = 充电（非 0），电量 offset 6。鼠标休眠不回帧。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "00 AA 12 00 00",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "charging": {
 "nonzero": true,
 "offset": 5
 },
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 6,
 "scale": 1.0
 },
 "min_length": 7,
 "status": {
 "offset": 1,
 "ok_values": [
 85
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "CROCIRIS"
 },
 "xiberia-t7": {
 "keywords": "XIBERIA T7 耳机",
 "known_ids": [
 {
 "pid": "",
 "vid": "36F9",
 "wired_pid": ""
 }
 ],
 "label": "西伯利亚 T7 / T7 GT 耳机",
 "match": {
 "require_pid_hit": false,
 "usage": null,
 "usage_page": "0xFF00"
 },
 "notes": "来源 XIBERIA HUB ActHID.dll 逆向：64 字节 55 65 00 00（报告 ID 0x55，命令 0x65 查电量）；回包 55 65 00 LL…，电量 offset 3；充电未提供。德盛方案，VID 36F9 全系按 FF00 命令口匹配（与 X7 的 FF0A 口不冲突）。",
 "request": {
 "in_len": null,
 "out_len": null,
 "payload_hex": "55 65 00 00",
 "report_id": null,
 "transport": "write_read"
 },
 "response": {
 "level": {
 "add": 0,
 "encoding": "u8",
 "max": 100,
 "min": 0,
 "offset": 3,
 "scale": 1.0
 },
 "min_length": 4,
 "status": {
 "offset": 0,
 "ok_values": [
 85
 ]
 }
 },
 "sampling": {
 "attempts": 3,
 "pick": "mode_nonzero",
 "request_timeout_ms": 1200,
 "stable_count": 2,
 "total_timeout_s": 4.5
 },
 "vendor": "西伯利亚 XIBERIA"
 }
}"""

BUILTIN: dict = json.loads(BUILTIN_JSON)
