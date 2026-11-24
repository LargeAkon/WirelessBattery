# -*- coding: utf-8 -*-
"""协议包解码自测：用参考项目里的真机报文当向量。

不碰硬件，只喂字节 —— 这些帧全部来自 vigil-watt 的单元测试与硬件文档，
所以这里过了，说明字节偏移和校验跟原项目一致。

第二批（雷蛇 / 迈从 / AULA / VGN / ATK / 索尼 / 北通 / GANSS / AKG / 寸渊影弑 /
雷柏 / 墨将 / Haute42 / HyperX CF2）的帧同样来自该项目的 xxxCodecTests.cs。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "app"))

from providers.packs import (          # noqa: E402
    ajazz, akg, asus, atk, aula, betop, cherry, darkrim, eweadn, gamesir, ganss,
    haute, hecate, hyperx_cf2, inphic_delux, lingbao, mchose, mojhon, pulsar,
    rapoo, razer, sony, thunderobot, vgn,
)

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'OK ' if ok else 'FAIL'} {name}: {got!r} 期望 {want!r}")
    if not ok:
        FAILS.append(name)


def hexb(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


# ---------------------------------------------------------------- 第一批
def test_pulsar() -> None:
    print("派世 Pulsar")
    status = hexb("080300000001006506710000000000006D")
    power = hexb("08040000000214000DF200000000000034")
    check("STATUS 请求帧", pulsar.build(pulsar.CMD_STATUS).hex().upper(),
          "080300000000000000000000000000004A")
    check("POWER 请求帧", pulsar.build(pulsar.CMD_POWER).hex().upper(),
          "0804000000000000000000000000000049")
    check("校验 STATUS", pulsar.checksum(status), status[-1])
    check("校验 POWER", pulsar.checksum(power), power[-1])
    check("STATUS 在线位", status[6], 0)
    check("POWER 电量", power[6], 20)
    check("POWER 充电位", power[7], 0)
    broken = bytearray(power)
    broken[-1] ^= 0xFF
    check("坏校验被拒", pulsar._reply(pulsar.CMD_POWER)(bytes(broken)), None)
    check("命令不符被拒", pulsar._reply(pulsar.CMD_STATUS)(power), None)


def test_cherry() -> None:
    print("CHERRY PIXIU75")

    def frame(block: int, length: int, payload: str) -> bytes:
        buf = bytearray(cherry.FRAME_LEN)
        buf[0] = cherry.REPORT_ID
        buf[3] = block
        buf[4] = length
        data = hexb(payload)
        buf[cherry.PAYLOAD_OFFSET:cherry.PAYLOAD_OFFSET + len(data)] = data
        return bytes(buf)

    info = frame(cherry.BLOCK_DEVICE_INFO, 0x18, "AA5500006A04E201010001000100")
    battery = frame(cherry.BLOCK_BATTERY, 4, "30000000")
    charging = frame(cherry.BLOCK_BATTERY, 4, "33010000")
    parse = cherry._reply(cherry.BLOCK_BATTERY)
    payload = cherry._reply(cherry.BLOCK_DEVICE_INFO)(info)
    pid = (payload[6] | (payload[7] << 8)) if payload and payload[:2] == b"\xAA\x55" else None
    check("设备信息块签名", payload[:2], b"\xAA\x55")
    check("设备信息 PID", pid, 0x01E2)
    check("电量 48%", parse(battery)[0], 0x30)
    check("充电位 0", parse(battery)[1], 0)
    check("电量 51% 充电", (parse(charging)[0], parse(charging)[1] & 1), (0x33, 1))
    req = cherry.build_request(cherry.BLOCK_BATTERY, 4, 0x0102)
    check("请求块号", req[3], 0x1A)
    check("请求偏移低/高", (req[5], req[6]), (0x02, 0x01))


def test_inphic_delux() -> None:
    print("英菲克 / DELUX")
    check("英菲克 85% 充电", inphic_delux._parse(bytes([0x03, 0x76, 0x41, 0x03, 85])),
          ("协议包·英菲克", "英菲克 ZHEN", 0x03, 85))
    check("DELUX 满电", inphic_delux._parse(bytes([0x30, 0x40, 0x02, 100]))[2:],
          (0x02, 100))
    check("非本协议", inphic_delux._parse(bytes([0x11, 0x22, 0x33, 0x44])), None)


def test_hecate() -> None:
    print("HECATE G5M Pro")
    frame = bytearray(64)
    frame[0] = 0x04
    frame[3] = 0x1A
    frame[8] = 77
    frame[9] = 0x01
    check("状态帧", hecate.parse(bytes(frame)), (77, True))
    frame[9] = 0x00
    check("放电", hecate.parse(bytes(frame)), (77, False))
    frame[8] = 0
    check("0% 视为瞬态", hecate.parse(bytes(frame)), None)
    check("查询帧标记", hecate.query_frame()[3], 0x1A)


def test_gamesir() -> None:
    print("盖世小鸡 G7 Pro")
    frame = bytearray(64)
    frame[0] = 0x12
    frame[35] = 0
    frame[36] = 88
    check("状态帧", gamesir.parse(bytes(frame)), (88, False))
    frame[35] = 1
    check("充电中", gamesir.parse(bytes(frame)), (88, True))
    frame[36] = 0
    check("0% 视为未就绪", gamesir.parse(bytes(frame)), None)
    check("心跳帧", gamesir.heartbeat()[:3], bytes([0x0F, 0xF2, 0x00]))


def test_ajazz() -> None:
    print("黑爵 AK870")
    frame = bytearray(65)
    frame[2] = 57
    frame[4] = 0
    frame[7] = 1
    check("电量 57%", ajazz.parse(bytes(frame)), 57)
    frame[4] = 1
    check("设备未连上", ajazz.parse(bytes(frame)), None)
    check("查询帧", ajazz.query_frame()[:8], bytes([0xF7, 0, 0, 0, 0, 0, 0, 0x08]))


def test_lingbao() -> None:
    print("凌豹 M5PRO Max")
    frame = bytearray(65)
    frame[0] = 0
    frame[1] = 1
    frame[2] = 0
    frame[3] = 74
    frame[4] = 1
    frame[5] = 1
    check("电量 74% 充电", lingbao.parse(bytes(frame)), (74, True))
    frame[3] = 1
    check("1% 视为占位", lingbao.parse(bytes(frame)), None)


def test_thunderobot() -> None:
    print("雷神 ML903")
    frame = bytearray(64)
    frame[0] = 0xA1
    frame[1] = 0x02
    frame[2] = 0x04
    frame[3] = 0xAA
    frame[4] = 0xBB
    frame[5] = 0x02
    frame[6] = 0x25
    frame[7] = 66
    check("TLV 电量 66%", thunderobot.parse(bytes(frame)), 66)
    frame[7] = 120
    check("越界电量整帧作废", thunderobot.parse(bytes(frame)), None)
    frame[7] = 66
    frame[40] = 1
    check("结束标记后非零作废", thunderobot.parse(bytes(frame)), None)


def test_eweadn() -> None:
    print("前行者 EWEADN")
    check("X87 85%", eweadn.parse_keyboard(bytes([0x20, 0x01, 0x00, 85])), 85)
    check("X87 0% 视为未就绪",
          eweadn.parse_keyboard(bytes([0x20, 0x01, 0x00, 0])), None)
    check("S9 73% 不充电",
          eweadn.parse_mouse(hexb("0350000B020149")), (73, False))
    check("S9 充电位", eweadn.parse_mouse(hexb("0350000B0201C9")), (73, True))
    frame = bytearray(eweadn.keyboard_query())
    frame[32] = 0                       # 校验位本身要按 0 参与求和
    check("X87 校验", eweadn.keyboard_query()[-1], sum(frame) & 0xFF)
    check("S9 CRC 范围", eweadn.mouse_query()[0],
          sum(eweadn.mouse_query()[1:]) & 0xFF)


def test_asus() -> None:
    print("华硕 ROG")
    kb = bytearray(64)
    kb[0] = 2
    kb[1] = 0x12
    kb[2] = 1
    kb[6] = 95
    kb[9] = 0
    check("键盘 95% 不充电", asus._parse_battery(bytes(kb)), (95, False))
    kb[9] = 1
    check("键盘充电位", asus._parse_battery(bytes(kb)), (95, True))

    paired = bytearray(64)
    paired[0] = 1
    paired[1] = 0xA0
    paired[3] = 1                      # 一条配对记录
    paired[5] = 0xAE
    paired[6] = 0x1A                   # PID 0x1AAE
    paired[7] = 2                      # keyboard report
    paired[8] = 4
    check("配对表认出 Scope", asus._parse_paired(bytes(paired)), 0x1AAE)
    paired[5] = 0x11
    paired[6] = 0x22
    check("别的键盘不认领", asus._parse_paired(bytes(paired)), None)

    hs = bytearray(64)
    hs[0] = 0xCC
    hs[1] = 0x12
    hs[2] = 0x07
    hs[6] = 88
    hs[7] = 20
    data = asus._parse_headset(asus.CMD_POWER)(bytes(hs))
    check("耳机电量字段", data[1], 88)
    hs[6] = 0xFE
    data = asus._parse_headset(asus.CMD_POWER)(bytes(hs))
    check("0xFE 是未就绪", data[1], 0xFE)


# ---------------------------------------------------------------- 第二批
def test_rapoo() -> None:
    print("雷柏 VT3 二代")
    # 真机：94% / 充电标志 1 / RF=0xC8（bit7=1）
    check("正常帧", rapoo.parse(hexb("071004800C800C015E000301001246010202C8")),
          (94, False, True))
    # 真机：断电瞬间 RF=0x7F（bit7=0）
    check("断链帧", rapoo.parse(hexb("071004800C800C015E0003010012460102027F")),
          (94, False, False))
    # 真机：重连后 95%，充电标志翻 0
    check("重连帧", rapoo.parse(hexb("071004800C800C005F000301001246010202D2")),
          (95, False, True))
    # 真机：有线 100%、充电标志 2、RF=0x00（有线无 RF 属正常）
    check("有线满电", rapoo.parse(hexb("0742021A041A04026400030100134B10000100")),
          (100, True, True))
    check("非 0x07 帧", rapoo.parse(hexb("041004800C800C015E000301001246010202C8")),
          None)
    dead = bytearray(hexb("071004800C800C015E000301001246010202C8"))
    dead[8] = 0
    check("0% 视为瞬态", rapoo.parse(bytes(dead)), None)


def test_atk() -> None:
    print("ATK / VXE")
    check("查询帧", atk.build_mouse_query().hex().upper(),
          "0804" + "00" * 14 + "49")
    # 真机：A9 Air 大师版+ 无线 65%
    check("无线 65%", atk.parse_mouse(hexb("08040000000241000FCD0000000000002A")),
          (65, False))
    # 真机：同鼠标插线 80% 充电
    check("有线 80% 充电",
          atk.parse_mouse(hexb("0804000000025001105E00000000000088")), (80, True))
    # 休眠时固件不回应；构造出来的 0% 帧必须被拒
    check("0% 占位被拒",
          atk.parse_mouse(hexb("0804010000000000000000000000000048")), None)
    # 鼠标移动报文不能被当成电量帧
    check("移动报文被拒",
          atk.parse_mouse(hexb("080102030405060708090A0B0C0D0E0F10")), None)
    check("VIA 查询帧", atk.build_via_query(9)[:5], bytes([0x00, 0x02, 0x96, 0x24, 0x00]))
    check("VIA 应答 72% 充电",
          atk.parse_via(bytes([0x00, 0x02, 0x96, 0x24, 72, 1])), (72, True))
    check("VIA 非本命令", atk.parse_via(bytes([0x00, 0x02, 0x97, 0x24, 72, 1])), None)


def test_vgn() -> None:
    print("VGN")
    # kc2：64 字节，命令 0x06 回显，电量在第 19 字节（bit7 = 充电）
    kc2 = bytearray(64)
    kc2[0] = 0xB3
    kc2[1] = vgn.KC2_CMD
    kc2[3:8] = bytes([1, 2, 3, 0, 5])
    kc2[1 + vgn.KC2_LEVEL] = 68 | 0x80
    check("kc2 68% 充电", vgn.parse_kc2(bytes(kc2)), (68, True))
    kc2[1 + vgn.KC2_LEVEL] = 68
    check("kc2 68% 放电", vgn.parse_kc2(bytes(kc2)), (68, False))
    blank = bytearray(64)
    blank[1] = vgn.KC2_CMD
    check("kc2 全零缓冲被拒", vgn.parse_kc2(bytes(blank)), None)

    # y2：17 字节，[0]=0x08 / [1]=0x04 / [15]=校验
    y2 = bytearray(16)
    y2[0] = vgn.Y2_CMD
    y2[1] = 0
    y2[3] = 1
    y2[4] = 2
    y2[5] = 41
    y2[6] = 1
    y2[15] = vgn.y2_checksum(bytes(y2))
    check("y2 41% 充电", vgn.parse_y2(bytes([vgn.Y2_RID]) + bytes(y2)), (41, True))
    bad = bytearray(y2)
    bad[15] ^= 0xFF
    check("y2 坏校验被拒", vgn.parse_y2(bytes([vgn.Y2_RID]) + bytes(bad)), None)

    # V98 Pro：0x04 / [3]=0x1A / 电量 [8]
    v98 = bytearray(20)
    v98[0] = vgn.V98_RID
    v98[3] = 0x1A
    v98[8] = 87
    v98[9] = 0
    check("V98 87%", vgn.parse_v98(bytes(v98)), (87, False))
    v98[9] = 1
    check("V98 充电", vgn.parse_v98(bytes(v98)), (87, True))
    v98[3] = 0x1B
    check("V98 非电量帧被拒", vgn.parse_v98(bytes(v98)), None)


def test_sony() -> None:
    print("索尼 INZONE / DualSense")
    check("H9 查询帧", sony.build_h9()[:12],
          bytes([0x02, 0x0C, 0x01, 0x00, 0xFC, 0x08, 0x96, 0xC3, 0x41, 0x04, 0x01, 0x01]))

    h9 = bytearray(64)
    h9[0] = sony.H9_RID
    h9[8] = sony.RESP_CLASS
    h9[9] = sony.CMD_BATTERY
    h9[10] = sony.FLAG_RESPONSE
    h9[13] = 0
    h9[14] = 62
    check("H9 62% 放电", sony.parse_h9(bytes(h9)), (62, False))
    h9[13] = 1
    check("H9 充电", sony.parse_h9(bytes(h9)), (62, True))
    h9[13] = 0xFF
    check("H9 充电位未知", sony.parse_h9(bytes(h9)), (62, None))
    h9[9] = 0x05
    check("H9 非电量命令被拒", sony.parse_h9(bytes(h9)), None)


def test_betop() -> None:
    print("北通 T9 / 鲲鹏20")
    # 状态帧：02 15 <电量> 00 <充电 nibble>
    check("状态帧 100% 充电",
          betop.parse_status(hexb("02156400510101000000000000000000")), (100, True))
    check("状态帧 93% 放电",
          betop.parse_status(hexb("02155D00500101000000000000000000")), (93, False))
    check("0% 未就绪", betop.parse_status(hexb("02150000500000000000000000000000")),
          None)
    check("越界 101%", betop.parse_status(hexb("02156500500000000000000000000000")),
          None)
    check("帧头不符", betop.parse_status(hexb("1325640051010100")), None)

    # T9：0x04 帧，[23] 是 0~120 的原始值
    t9 = bytearray(24)
    t9[0] = betop.T9_RID
    t9[betop.T9_BATTERY_INDEX] = 60
    check("T9 60/120 = 50%", betop.parse_t9(bytes(t9)), (50, False))
    t9[betop.T9_BATTERY_INDEX] = betop.T9_NOT_LINKED
    check("T9 未连上占位", betop.parse_t9(bytes(t9)), None)
    t9[betop.T9_BATTERY_INDEX] = betop.T9_FULL
    check("T9 满电", betop.parse_t9(bytes(t9)), (100, False))
    check("查询帧", betop.build_query(16)[:2], bytes([betop.STATUS_RID, betop.STATUS_HEADER]))


def test_aula() -> None:
    print("狼蛛 AULA")
    # G9：0xAB + 47 4D 86
    g9 = bytearray(64)
    g9[0] = aula.G9_RID
    g9[1:4] = bytes([0x47, 0x4D, 0x86])
    g9[aula.G9_LEVEL] = 76
    g9[aula.G9_CHARGE] = 0x02
    check("G9 76% 充电", aula.g9_parse(bytes(g9)), (76, True))
    g9[aula.G9_CHARGE] = 0
    check("G9 76% 放电", aula.g9_parse(bytes(g9)), (76, False))
    g9[aula.G9_LEVEL] = 0
    check("G9 全零视为旧固件不报数", aula.g9_parse(bytes(g9)), None)
    g9[aula.G9_LEVEL] = 50
    g9[3] = 0x85
    check("G9 帧头不符", aula.g9_parse(bytes(g9)), None)

    # L9：0A 81 …，电量 [18] / 充电 [17]
    l9 = bytearray(24)
    l9[0] = aula.L9_IN_ID
    l9[1] = aula.L9_CMD
    l9[aula.L9_LEVEL_INDEX] = 55
    l9[aula.L9_CHARGE_INDEX] = 1
    check("L9 55% 充电", aula.l9_parse(bytes(l9)), (55, True))
    l9[0] = 0x0B
    check("L9 应答号不符", aula.l9_parse(bytes(l9)), None)

    # V1 帧（F99 Pro / 迈从键盘）：推送 0x0A / 应答 0x4A
    push = bytearray(20)
    push[0] = aula.V1_RID
    push[1] = aula.V1_PUSH
    push[5] = aula.V1_PUSH_BATTERY
    push[6] = 47
    push[7] = 0x10
    check("V1 推送 47% 充电", aula.v1_read(bytes(push)), (47, True))
    push[7] = 0
    check("V1 推送 47% 放电", aula.v1_read(bytes(push)), (47, False))
    push[5] = 0x06
    check("V1 非电量推送", aula.v1_read(bytes(push)), None)

    reply = bytearray(20)
    reply[0] = aula.V1_RID
    reply[1] = aula.V1_QUERY
    reply[5] = 66
    reply[6] = 0
    check("V1 应答 66%", aula.v1_read(bytes(reply)), (66, False))
    reply[5] = 0
    check("V1 应答 0% 被拒", aula.v1_read(bytes(reply)), None)

    # HERO 68 Air：应答帧 [0]=命令 / [1]=参数 / [5]=长度 / 尾部让 sum+ID = 0xFF
    hero = bytearray(aula.HERO_PACKET)
    hero[0] = 0x87
    hero[1] = 0
    hero[2] = 0
    hero[3] = 1
    hero[4] = 0
    hero[5] = 2
    hero[6] = 74
    hero[7] = 0
    hero[-1] = (255 - (sum(hero[:-1]) + aula.HERO_RID)) & 0xFF
    check("HERO 74% 放电", aula.hero_parse_battery(bytes(hero)), (74, False))
    hero[7] = 0x10
    hero[-1] = (255 - (sum(hero[:-1]) + aula.HERO_RID)) & 0xFF
    check("HERO 74% 充电", aula.hero_parse_battery(bytes(hero)), (74, True))


def test_hyperx_cf2() -> None:
    print("HyperX Cloud Flight 2")
    check("心跳被排除", hyperx_cf2.parse(hexb("45020000")), None)
    check("心跳（长帧）被排除", hyperx_cf2.parse(bytes([0xFF] + [0] * 14 + [0x44] + [0] * 8)), None)
    check("51 02 帧 94%", hyperx_cf2.parse(hexb("51025E") + bytes(61)), (94, None))
    check("充电事件", hyperx_cf2.parse(hexb("FB090100")), (None, True))
    check("放电事件", hyperx_cf2.parse(hexb("FB090000")), (None, False))
    check("电量事件 94%", hyperx_cf2.parse(hexb("FB1300" + "5E" + "000000")), (94, None))
    check("未知子命令", hyperx_cf2.parse(hexb("FB110000")), None)


def test_razer() -> None:
    print("雷蛇")
    # 经典 90 字节：请求帧 [1]=事务号 / [5]=2 / [6]=0x07 / [7]=命令 / [88]=校验
    req = razer.classic_request(razer.CMD_BATTERY, razer.CLASSIC_TXN)
    check("经典请求长度", len(req), razer.CLASSIC_PAYLOAD)
    check("经典请求命令区", (req[1], req[5], req[6], req[7]),
          (razer.CLASSIC_TXN, 0x02, razer.CLASS_BATTERY, razer.CMD_BATTERY))
    check("经典请求校验", req[88], razer.classic_checksum(req))

    reply = bytearray(razer.CLASSIC_BUFFER)
    reply[1] = razer.STATUS_OK
    reply[7] = razer.CLASS_BATTERY
    reply[8] = razer.CMD_BATTERY
    reply[10] = 204
    check("经典回显判定", razer.classic_echo(bytes(reply), razer.CMD_BATTERY), True)
    check("经典 204/255 = 80%", razer.classic_percent(bytes(reply)), 80)
    busy = bytearray(reply)
    busy[1] = razer.STATUS_BUSY
    check("忙状态不算回显", razer.classic_echo(bytes(busy), razer.CMD_BATTERY), False)

    # Viper SE：91 字节，[0]=0，payload 从 [1] 开始
    se = bytearray(razer.CLASSIC_BUFFER)
    se[0] = 0
    se[1] = razer.STATUS_OK
    se[2] = razer.CLASSIC_TXN
    se[3] = se[4] = se[5] = 0
    se[6] = 2
    se[7] = razer.CLASS_BATTERY
    se[8] = razer.CMD_BATTERY
    se[10] = 128
    se[89] = razer.classic_checksum(se[1:])
    se[90] = 0
    check("SE 128/255 ≈ 50%", razer.se_parse(bytes(se)), (128 * 100 + 127) // 255)
    se[90] = 1
    check("SE 尾部非零被拒", razer.se_parse(bytes(se)), None)

    # PA 耳机：真机 79% 放电
    pa = hexb("020E504908CE92DE050004002101014F4901C00C6B00000300119313000000000000000000000000000000000000000000000000000000000000000000000000")
    check("PA 耳机电量 79%", razer.pa_parse(pa, razer.PA_BATTERY), 79)
    pa_charge = hexb("020E504908CFB6E0050004002A0101004901C00C6B00000300119313000000000000000000000000000000000000000000000000000000000000000000000000")
    check("PA 耳机放电标志", razer.pa_parse(pa_charge, razer.PA_CHARGING), 0)
    check("PA 命令不符被拒", razer.pa_parse(pa, razer.PA_CHARGING), None)

    # Kraken V4：真机 63% 放电
    kraken = hexb("020260000000050080802101013F0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000007900")
    check("Kraken 63%", razer.kraken_parse(kraken, razer.KRAKEN_BATTERY), 63)
    kraken_charge = hexb("020260000000050080802A0101000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000004D00")
    check("Kraken 未充电", razer.kraken_parse(kraken_charge, razer.KRAKEN_CHARGING), 0)
    check("Kraken 查询帧头", razer.kraken_query(razer.KRAKEN_BATTERY)[:13].hex().upper(),
          "02006000000004000080210000")


def test_mchose() -> None:
    print("迈从 MCHOSE")
    # V1 帧（键盘）：推送 0x0A / 应答 0x4A，充电位在 bit4
    push = bytearray(mchose.V1_LEN)
    push[0] = mchose.V1_RID
    push[1] = mchose.V1_PUSH
    push[5] = mchose.V1_PUSH_BATTERY
    push[6] = 52
    push[7] = 0x10
    check("V1 推送 52% 充电", mchose.v1_read(bytes(push)), (52, True))
    push[7] = 0
    check("V1 推送 52% 放电", mchose.v1_read(bytes(push)), (52, False))
    push[6] = 1
    check("V1 1% 视为占位", mchose.v1_read(bytes(push)), None)

    reply = bytearray(mchose.V1_LEN)
    reply[0] = mchose.V1_RID
    reply[1] = mchose.V1_QUERY
    reply[5] = 39
    reply[6] = 0
    check("V1 应答 39%", mchose.v1_read(bytes(reply)), (39, False))

    # 会话帧里的型号密码：G87
    session = bytearray(mchose.V1_LEN)
    session[0] = mchose.V1_RID
    session[1] = mchose.V1_SESSION
    session[2] = 0x01
    session[5:11] = bytes.fromhex("03000000021C")
    check("会话型号 G87", mchose.v1_model(bytes(session)), "G87")
    session[5:11] = bytes.fromhex("FFFFFFFFFFFF")
    check("未知型号密码", mchose.v1_model(bytes(session)), None)

    # 鼠标 V2：整帧取反，[0]=0xE2，[3]=充电，[4]=电量
    v2 = bytearray(16)
    v2[0] = mchose.V2_STATUS ^ 0xFF
    v2[3] = 0x01 ^ 0xFF
    v2[4] = 61 ^ 0xFF
    check("V2 反码 61% 充电", mchose.v2_parse(bytes(v2)), (61, True))
    v2[3] = 0x00 ^ 0xFF
    check("V2 反码 61% 放电", mchose.v2_parse(bytes(v2)), (61, False))
    v2[4] = 0 ^ 0xFF
    check("V2 0% 被拒", mchose.v2_parse(bytes(v2)), None)
    check("V2 poke 帧", mchose.v2_poke(16)[:2],
          bytes([mchose.V2_POKE_RID, mchose.V2_POKE_CMD ^ 0xFF]))

    # K7：4D 01 01 <len> <cmd lo> <cmd hi> …，电量在载荷 +12
    payload = bytearray(16)
    payload[10] = 1                    # 已连接
    payload[11] = 1                    # 充电
    payload[12] = 84                   # 电量
    frame = mchose.k7_frame(0x0900, bytes(payload))
    check("K7 84% 充电/已连接", mchose.k7_parse(frame), (84, 1, 1))
    check("K7 命令不符被拒", mchose.k7_parse(frame, ), (84, 1, 1))
    other = mchose.k7_frame(0x0901, bytes(payload))
    check("K7 另一命令读不到电量", mchose.k7_parse(other), None)

    # Gmouse：AA 30 …
    gm = bytearray(16)
    gm[0] = 0xAA
    gm[1] = 0x30
    gm[8] = 44
    gm[9] = 0
    check("Gmouse 44%", mchose.gmouse_parse(bytes(gm)), (44, False))
    gm[9] = 1
    check("Gmouse 充电", mchose.gmouse_parse(bytes(gm)), (44, True))
    check("Gmouse 查询帧", mchose.gmouse_query()[1:9],
          bytes([0x55, 0x30, 0xA5, 0x0B, 0x2E, 0x01, 0x01, 0x01]))

    # A5 V2 Ultra：反码 feature 0x11
    a5 = bytearray(21)
    a5[0] = 0x11
    a5[1] = 0xF9
    a5[2] = 0xE4 ^ 0xFF
    a5[3] = 0x41 ^ 0xFF
    a5[4] = 0x01 ^ 0xFF
    a5[5] = 0x11 ^ 0xFF
    a5[11] = 73 ^ 0xFF
    a5[12] = 1 ^ 0xFF
    check("A5 73% 充电", mchose.a5_parse(bytes(a5)), (73, True))
    a5[12] = 2 ^ 0xFF
    check("A5 充电位未知", mchose.a5_parse(bytes(a5)), (73, None))
    a5[3] = 0x00
    check("A5 VID 不符被拒", mchose.a5_parse(bytes(a5)), None)

    # 耳机 V9 / X9：55 65 …
    hs = bytearray(mchose.HS_LEN)
    hs[0] = mchose.HS_RID
    hs[1] = mchose.HS_ECHO
    hs[2] = 64
    hs[3] = 0x03
    check("耳机 64% 充电", mchose.hs_parse(bytes(hs), True), (64, True))
    hs[3] = 0x02
    check("耳机 64% 放电", mchose.hs_parse(bytes(hs), True), (64, False))
    check("耳机回显被拒", mchose.hs_parse(mchose.hs_query(), True), None)
    check("耳机查询帧头", mchose.hs_query()[:3],
          bytes([mchose.HS_RID, mchose.HS_ECHO, 0x01]))

    # 新代 dongle（QHW）：握手 4D AA 55 AA 55 AA 55，查询 4D 01 03 00 04 09 …
    hs_frame = mchose.qhw_handshake(64)
    check("QHW 握手帧头", hs_frame[:7],
          bytes([mchose.QHW_RID]) + bytes([0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55]))
    q = mchose.qhw_query(64)
    check("QHW 查询命令", q[:6], bytes([0x4D, 0x01, 0x03, 0x00, 0x04, 0x09]))
    check("QHW 查询校验", q[8], q[1] ^ q[2] ^ q[3] ^ q[4] ^ q[5] ^ q[6] ^ q[7])
    reply = bytes([0x4D, 0x01, 0x00, 0x00, 0x04, 0x09, 0x00, 0x01, 0x00, 82]) + bytes(54)
    check("QHW 应答 82% 放电", mchose.qhw_parse(reply), (82, False))
    reply = bytes([0x4D, 0x01, 0x00, 0x00, 0x04, 0x09, 0x00, 0x01, 0x01, 82]) + bytes(54)
    check("QHW 应答 82% 充电", mchose.qhw_parse(reply), (82, True))
    reply = bytes([0x4D, 0x01, 0x00, 0x00, 0x04, 0x09, 0x00, 0x01, 0x00, 1]) + bytes(54)
    check("QHW 1% 占位帧被拒", mchose.qhw_parse(reply), None)
    reply = bytes([0x4D, 0x01, 0x00, 0x00, 0x05, 0x09, 0x00, 0x01, 0x00, 82]) + bytes(54)
    check("QHW 命令不符被拒", mchose.qhw_parse(reply), None)
    push = bytes([0xFA, 0xFB, 0x07, 79, 1]) + bytes(59)
    check("QHW CZ 推送 79% 充电", mchose.qhw_parse_push(push), (79, True))
    push = bytes([0xFA, 0xFB, 0x07, 0, 0]) + bytes(59)
    check("QHW CZ 0% 被拒", mchose.qhw_parse_push(push), None)


def test_akg() -> None:
    print("AKG N9 Hybrid")

    def report(payload: bytes) -> bytes:
        frame = bytearray(akg.REPORT_LEN)
        frame[0] = akg.INPUT_ID
        frame[1] = len(payload)
        frame[2] = 0x80
        frame[3:3 + len(payload)] = payload
        return bytes(frame)

    # 真机：62 字节应答里前两段是 ACK + 50% 电量，后面是旧缓存
    raw = hexb("071080055B0300D60C00055D0500D60C00003201090500000A0700055D0800010905"
               "0000010400055D0800010905000"
               "00A0700055D080001090500000104".replace(" ", ""))
    hit = akg.take_payload(raw)
    check("报文长度字段", hit[:3].hex().upper(), "055B03")
    pending = bytearray(hit)
    messages = akg.take_messages(pending)
    check("切出两条完整消息", len(messages), 2)
    check("第一条是 ACK", messages[0][1], 0x5B)
    check("第二条电量 50%", akg.parse_battery(messages[1]), 50)
    check("ACK 不算电量", akg.parse_battery(messages[0]), None)

    # 异常结构必须整段丢弃
    check("非 0x07 报告被拒", akg.take_payload(bytes([0x08] + [0] * 61)), None)
    check("超长载荷被拒", akg.take_payload(bytes([0x07, 60, 0x80] + [0] * 59)), None)
    check("消息头不符", akg.take_messages(bytearray(b"\x06\x5D\x03\x00")), None)
    check("查询帧", akg.QUERY[:10].hex().upper(), "060780055A0300D60C00")


def test_darkrim() -> None:
    print("寸渊影弑")
    # 真机电量通知：单值形态 0x5A = 90%
    frame = hexb("FE00110003000003000101" + "5A98B4")
    check("单值 90%", darkrim.parse_battery(frame), (90, False))
    charge = bytearray(frame)
    charge[-3] = 0x5A | darkrim.CHARGE_BIT
    charge[-2:] = b"\x00\x00"
    # 改字节后 CRC 必然不符 → 用构造器重新算一遍才谈得上测充电位
    check("坏 CRC 整帧作废", darkrim.parse_battery(bytes(charge)), None)
    # GetVersion 应答不含电量
    check("版本帧不含电量",
          darkrim.parse_battery(hexb("FE0010000200000E00FF0C0102082302020300030201003AEF")),
          None)
    check("请求帧被回显不算应答",
          darkrim.parse_battery(darkrim.build_request(0)), None)


def test_mojhon() -> None:
    print("墨将 烈风2")
    check("读电量请求帧", mojhon.build_read(mojhon.REGISTER_BATTERY)[:4],
          bytes([0xA5, 4, mojhon.REGISTER_BATTERY,
                 (0xA5 + 4 + mojhon.REGISTER_BATTERY) & 0xFF]))
    # 帧长字节 = 含头尾的总长度；校验 = 除末字节外全部之和
    body = bytes([0xA4, 5, mojhon.REGISTER_BATTERY, 81])
    frame = body + bytes([mojhon.checksum(body)])
    check("81% 标志未知", mojhon.parse_reply(frame), (81, None))
    body2 = bytes([0xA4, 6, mojhon.REGISTER_BATTERY, 81, 1])
    check("81% 充电位 1",
          mojhon.parse_reply(body2 + bytes([mojhon.checksum(body2)])), (81, True))
    body3 = bytes([0xA4, 6, mojhon.REGISTER_BATTERY, 81, 0])
    check("81% 充电位 0",
          mojhon.parse_reply(body3 + bytes([mojhon.checksum(body3)])), (81, False))
    body4 = bytes([0xA4, 5, mojhon.REGISTER_NAME, 81])
    check("别的寄存器不算电量",
          mojhon.parse_reply(body4 + bytes([mojhon.checksum(body4)])), None)
    body5 = bytes([0xA4, 5, mojhon.REGISTER_BATTERY, 120])
    check("越界电量被拒",
          mojhon.parse_reply(body5 + bytes([mojhon.checksum(body5)])), None)
    bad = body + bytes([(mojhon.checksum(body) + 1) & 0xFF])
    check("坏校验被拒", mojhon.parse_reply(bad), None)


def test_haute() -> None:
    print("Haute42 Adapter 4DS")
    status = bytearray(20)
    status[0] = haute.STATUS_ID
    status[haute.PERCENT_INDEX] = 57
    status[haute.CHARGE_INDEX] = 1
    check("57% 充电", haute.parse_status(bytes(status)), (57, True))
    status[haute.CHARGE_INDEX] = 0x10            # 高四位是别的标志
    check("只看低四位", haute.parse_status(bytes(status)), (57, False))
    status[haute.PERCENT_INDEX] = 0xFF
    check("0xFF 表示这帧没带电量", haute.parse_status(bytes(status)), (None, None))
    status[haute.PERCENT_INDEX] = 57
    status[0] = 0xF8
    check("非 0xF9 帧被拒", haute.parse_status(bytes(status)), None)


def test_ganss() -> None:
    print("GANSS / 狼蛛 F108 Pro")
    payload = bytearray(32)
    payload[0] = 0x20
    payload[1] = 0x01
    payload[2] = 0x00
    payload[3] = 97
    payload[-1] = sum(payload[:-1]) & 0xFF
    check("带 ID 的 33 字节帧", ganss.parse(bytes([0x00]) + bytes(payload)), 97)
    check("不带 ID 的 32 字节帧", ganss.parse(bytes(payload)), 97)
    broken = bytearray(payload)
    broken[-1] ^= 0xFF
    check("坏校验被拒", ganss.parse(bytes(broken)), None)
    zero = bytearray(payload)
    zero[3] = 0
    zero[-1] = sum(zero[:-1]) & 0xFF
    check("0% 被拒", ganss.parse(bytes(zero)), None)
    check("查询帧", ganss.query_frame()[:3], bytes([0x00, 0x20, 0x01]))


def main() -> int:
    for fn in (test_pulsar, test_cherry, test_inphic_delux, test_hecate,
               test_gamesir, test_ajazz, test_lingbao, test_thunderobot,
               test_eweadn, test_asus,
               test_rapoo, test_atk, test_vgn, test_sony, test_betop, test_aula,
               test_hyperx_cf2, test_razer, test_mchose, test_akg, test_darkrim,
               test_mojhon, test_haute, test_ganss):
        fn()
    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: {', '.join(FAILS)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
