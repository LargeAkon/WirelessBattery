# -*- coding: utf-8 -*-
"""协议解析与合并规则的离线测试，不打开真实设备。"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from model import Device, KEYBOARD, MOUSE  # noqa: E402
from providers import proto, raw_hid  # noqa: E402
from providers.hid_desc import extract_bits, parse_battery_fields, to_percent  # noqa: E402
from scanner import Scanner  # noqa: E402
from config import Config  # noqa: E402


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise SystemExit(f"FAIL {name}")
    print("ok", name)


def test_compx() -> None:
    req = proto.compx_request()
    _check("compx checksum byte", req[16] == 0x49)
    _check("compx sum", (sum(req) & 0xFF) == 0x55)
    good = bytearray(req)
    good[6] = 35
    good[7] = 0
    good[16] = (0x55 - (sum(good[:16]) & 0xFF)) & 0xFF
    parsed = proto.parse_compx(bytes(good))
    _check("compx level", parsed == (35.0, False))
    bad = bytearray(good)
    bad[16] ^= 0xFF
    _check("compx reject bad sum", proto.parse_compx(bytes(bad)) is None)


def test_hidpp_version() -> None:
    _check("c54d version", proto.parse_hidpp_version(bytes([0x00, 0x00, 0x02])) == (2, 0))
    _check("hidpp4 marker", proto.parse_hidpp_version(bytes([0x00, 0x00, 0x04])) == (4, 0))
    _check("hidpp level", proto.parse_hidpp20_level(bytes([64, 50, 0])) == (64.0, False))
    _check("hidpp charging", proto.parse_hidpp20_level(bytes([80, 0, 1])) == (80.0, True))
    _check("hidpp unknown", proto.parse_hidpp20_level(bytes([0, 0, 1])) is None)
    _check("hidpp voltage", proto.parse_hidpp20_voltage(bytes([0x0E, 0xE3, 0x80])) == (50.0, True))
    _check("hidpp unified coarse", proto.parse_hidpp20_unified(bytes([0, 8, 3])) == (100.0, True))
    _check("hidpp20 version", proto.parse_hidpp_version(bytes([4, 2])) == (4, 2))
    _check("empty version", proto.parse_hidpp_version(b"") is None)


def test_hidpp10() -> None:
    _check("mileage", proto.parse_hidpp10_mileage(bytes([42, 0, 0x40])) == (42.0, True))
    _check("mileage discharge", proto.parse_hidpp10_mileage(bytes([80, 0, 0x00])) == (80.0, False))
    _check("status full", proto.parse_hidpp10_status(bytes([7, 0x00])) == (90.0, False))
    _check("status charging", proto.parse_hidpp10_status(bytes([5, 0x21])) == (55.0, True))
    _check("status junk", proto.parse_hidpp10_status(bytes([9, 0x00])) is None)


def test_razer() -> None:
    report = proto.razer_feature(0x1F, 0x80)
    body = report[1:]
    crc = 0
    for i in range(2, 88):
        crc ^= body[i]
    _check("razer crc", body[88] == (crc & 0xFF))
    reply = bytearray(91)
    reply[1] = 0x02
    reply[7] = 0x07
    reply[8] = 0x80
    reply[10] = 255
    _check("razer full", proto.parse_razer_battery(bytes(reply)) == 100.0)
    reply[10] = 0
    _check("razer empty", proto.parse_razer_battery(bytes(reply)) == 0.0)
    reply[1] = 0x00
    _check("razer reject", proto.parse_razer_battery(bytes(reply)) is None)
    bare = bytearray(10)
    bare[0] = 0x02
    bare[6] = 0x07
    bare[7] = 0x80
    bare[9] = 128
    _check("razer no report id", proto.parse_razer_battery(bytes(bare)) == 50.0)


def test_others() -> None:
    asus = bytes([0x03, 0x12, 0x07, 0x00, 0x00, 53, 0x02, 0x14, 0xFD, 0x0E, 0x00])
    _check("asus", proto.parse_asus(asus) == (53.0, False))
    _check("asus standby", proto.parse_asus(bytes([0x00, 0x12, 0x07, 0, 0, 0, 0, 0, 0, 0, 0])) is None)
    feature = bytearray(16)
    feature[6] = 0x83
    feature[7] = 1
    feature[8] = 41
    _check("feature83", proto.parse_feature83(bytes(feature)) == (41.0, True))
    feature[7] = 2
    _check("feature83 full", proto.parse_feature83(bytes(feature)) == (41.0, True))
    shifted = bytearray(16)
    shifted[5] = 0x83
    shifted[6] = 0
    shifted[7] = 77
    _check("feature83 shifted", proto.parse_feature83(bytes(shifted)) == (77.0, False))
    _check("feature83 junk", proto.parse_feature83(bytes(16)) is None)
    _check("asus shifted", proto.parse_asus(bytes([0x12, 0x07, 0, 0, 40, 0, 0, 0, 0, 1])) == (40.0, True))
    keyboard = bytes([0x02, 0x12, 0x01, 0, 0, 0, 77, 0, 0, 1])
    _check("asus keyboard", proto.parse_asus(keyboard) == (77.0, True))
    tenths = bytearray(17)
    tenths[0] = 0x09
    tenths[1] = 0x04
    tenths[6] = 8
    tenths[16] = (0x55 - (sum(tenths[:16]) & 0xFF)) & 0xFF
    _check("areson tenths", proto.parse_compx(bytes(tenths), tenths=True) == (80.0, False))
    _check("nordic nines stay", proto.parse_compx(bytes(tenths)) == (8.0, False))


def test_hyperx() -> None:
    battery = bytes([0x66, 0x89, 0x0E, 0xD7, 48])
    _check("cloud iii", proto.parse_hyperx_66_battery(battery) == 48.0)
    _check("cloud iii offline", proto.parse_hyperx_66_battery(bytes([0x66, 0x89, 0, 0, 48])) is None)
    _check("cloud iii charge", proto.parse_hyperx_66_charging(bytes([0x66, 0x8A, 1, 0])) is True)
    iiis = bytearray(8)
    iiis[0] = 0x0C
    iiis[5] = 0x06
    iiis[6] = 89
    _check("cloud iii s", proto.parse_hyperx_iiis_battery(bytes(iiis)) == 89.0)
    alpha2 = bytes([0x51, 0x02, 67, 0, 0, 0, 0x80])
    _check("alpha2", proto.parse_hyperx_alpha2(alpha2) == (67.0, True))
    flight = bytes([0x21, 0xFF, 0x05, 0x0E, 0xC2])  # 3778 mV -> 45%
    _check("flight", proto.parse_hyperx_flight(flight) == (45.0, False))
    charging = bytes([0x21, 0xFF, 0x05, 17, 0])
    _check("flight charge", proto.parse_hyperx_flight(charging) == (None, True))
    dts = bytes([0x06, 0xFF, 0xBB, 0x02, 0, 0, 0, 70])
    _check("cloud ii", proto.parse_hyperx_ii_dts_battery(dts) == 70.0)
    kingston = bytes([0x0B, 0x00, 0xBB, 0x02, 0, 0, 0, 55])
    _check("kingston", proto.parse_hyperx_kingston_battery(kingston) == 55.0)


def test_brand_frames() -> None:
    n54 = bytes([0x08, 0x72, 0x00, 0x3A, 0x00, 0x07, 0x01, 100, 0x16, 0x11])
    _check("nordic54", proto.parse_nordic54(n54) == 100.0)
    asleep = bytearray(n54)
    asleep[2] = 0x01
    _check("nordic54 asleep", proto.parse_nordic54(bytes(asleep)) is None)
    _check("arctis gen2", proto.parse_arctis(bytes([0xB0, 0x03, 88, 0x01]), True) == (88.0, True))
    _check("arctis low ambiguous", proto.parse_arctis(bytes([0xB0, 0x03, 4, 0x00]), False) is None)
    _check("arctis low known", proto.parse_arctis(bytes([0xB0, 0x03, 4, 0x00]), True) == (4.0, False))
    _check("aerox", proto.parse_aerox(bytes([0xD2, 0x04])) == (15.0, False))
    _check("aerox charge", proto.parse_aerox(bytes([0xD2, 0x84])) == (15.0, True))
    _check("aerox asleep", proto.parse_aerox(bytes([0xD2, 0x00])) is None)
    _check("rival3", proto.parse_rival3(bytes([0xAA, 42, 0x00, 0x01])) == (42.0, True))
    _check("jbl", proto.parse_jbl(bytes([0x08, 95])) == 95.0)
    info = bytearray(12)
    info[0] = 0x5A
    info[1] = 0xA5
    info[2] = 0x01
    info[11] = 0x05
    _check("flydigi", proto.parse_flydigi(bytes(info)) == (100.0, False))
    info[11] = 0x15
    _check("flydigi charge", proto.parse_flydigi(bytes(info)) == (100.0, True))
    stick = bytearray(info)
    stick[2] = 0xEF
    stick[11] = 0x05
    _check("flydigi ignore sticks", proto.parse_flydigi(bytes(stick)) is None)
    g7 = bytes([0xAA, 0x30, 0xA5, 0x0B, 0x0A, 0x01, 0x01, 0x01, 0x2E, 0x00])
    _check("mchose g7", proto.parse_mchose_g7(g7) == (46.0, False))
    from brands import ARCTIS_DIRECT, FEATURE83, describe
    _check("lamzu vid", 0x373E in FEATURE83)
    _check("arctis pid", 0x22A1 in ARCTIS_DIRECT)
    text = describe(0x3554) or ""
    _check("compx brands", "Pulsar" in text and "达尔优" in text)


def test_descriptor() -> None:
    desc = bytes([
        0x05, 0x06, 0x09, 0x20, 0x15, 0x00, 0x25, 0x64,
        0x75, 0x08, 0x95, 0x01, 0x81, 0x02,
    ])
    fields = parse_battery_fields(desc)
    _check("one field", len(fields) == 1 and fields[0]["kind"] == "in")
    _check("offset", fields[0]["bit_offset"] == 0 and fields[0]["bit_size"] == 8)
    value = extract_bits(b"\x2A", 0, 8)
    _check("bits", to_percent(value, 100) == 42.0)
    _check("coarse", to_percent(5, 7) == 71.0)
    _check("wide scale", to_percent(255, 255) == 100.0)


def test_endpoints() -> None:
    """端点角色表不依赖设备，纯函数 —— 常量和函数一起被删过一次。"""
    _check("role vendor long", raw_hid._role_of(0xFF02, 0x0002) == "厂商协议·长报文")
    _check("role vendor short", raw_hid._role_of(0xFF00, 0x0001) == "厂商协议·短报文")
    _check("role vendor other", raw_hid._role_of(0xFF05, 0x0003) == "厂商协议")
    _check("role standard mouse", raw_hid._role_of(0x0001, 0x0002) == "鼠标")
    _check("role standard keyboard", raw_hid._role_of(0x0001, 0x0006) == "键盘")
    _check("role fallback", raw_hid._role_of(0x0003, 0x0009) == "标准用途")


def test_merge() -> None:
    scanner = Scanner(Config())
    # 「添加设备」写的协议与专用通道读到同一只接收器：只留专用通道那条
    manual = Device(key="m1", name="VXE R1", kind=MOUSE, level=30,
                    source="已添加·VXE", vid_pid="3554:F508", raw={"phys": "P"})
    native = Device(key="n1", name="VXE R1", kind=MOUSE, level=33,
                    source="Compx 电量", vid_pid="3554:F508", raw={"phys": "P"})
    kept = scanner._dedupe_channels([manual, native], [])
    _check("drop added copy", [d.key for d in kept] == ["n1"])

    # 同一型号的两只接收器各留一条
    a = Device(key="a", name="USB Receiver", kind=MOUSE, level=1,
               source="协议包·VGN", vid_pid="258A:1007", raw={"phys": "one"})
    b = Device(key="b", name="USB Receiver", kind=MOUSE, level=2,
               source="协议包·VGN", vid_pid="258A:1007", raw={"phys": "two"})
    merged = scanner._merge([a, b], [])
    _check("two receivers stay", len(merged) == 2)


def test_input_guard() -> None:
    """打字让位：厂商帧不能插进用户输入中间。

    320F:5088 这类接收器把键盘与厂商 collection 挂在同一个 USB 接口上，
    发一帧就要占用键击上报的通道。早期的 14 秒慢窗口发 9 帧，导致开机
    扫描那十几秒打字发涩。这里锁住三条不能再退回去的约束：
    一轮最多两帧、确认过写法后不再发无效帧、用户忙时一帧都不发。
    """
    from providers import evision, inputidle
    from providers.packs import base

    _check("未确认写法最多两帧",
           len(evision._order("guard", slow=False)) <= evision.MAX_FRAMES)
    _check("未确认慢路径最多两帧",
           len(evision._order("guard", slow=True)) <= evision.MAX_FRAMES)

    evision._VARIANT["guard"] = 1
    _check("确认后只发那一套", evision._order("guard", slow=False) == [1])
    _check("慢协议补发同款", evision._order("guard", slow=True) == [1, 1])
    evision._VARIANT.pop("guard", None)

    original = inputidle.idle_seconds
    try:
        # 用户一直在敲键盘：必须返回 False 让调用方放弃，而不是等一会儿硬发
        inputidle.idle_seconds = lambda: 0.05
        _check("持续输入时让位", inputidle.wait_idle(need=0.6, limit=0.2) is False)

        class FakeDev:
            def __init__(self) -> None:
                self.writes = 0

            def write(self, _frame) -> None:
                self.writes += 1

        dev = FakeDev()
        _check("让位时不发帧", base.write(dev, b"\x00" * 8) is False)
        _check("让位时没真写", dev.writes == 0)
        _check("让位有标记", base.deferred() is True)

        # 让位不是设备故障：不能进冷却，否则用户打一会儿字就被关 150 秒
        key = ("guard-test",)
        base._FAIL.pop(key, None)
        base.mark_fail(key)
        _check("让位不进冷却", key not in base._FAIL)

        # 用户停手后必须正常放行
        inputidle.idle_seconds = lambda: 5.0
        _check("空闲时放行", inputidle.wait_idle(need=0.6, limit=0.2) is True)
        dev2 = FakeDev()
        _check("放行后正常发帧", base.write(dev2, b"\x00" * 8) is True)
        _check("确实写了一帧", dev2.writes == 1)
        _check("放行后标记复位", base.deferred() is False)
    finally:
        inputidle.idle_seconds = original
        base._FAIL.pop(("guard-test",), None)


def test_packs_layout() -> None:
    """协议包目录：类型 → 品牌 → 型号。每个模块都要写清适配什么设备。

    开源之后别人加设备是照着现有文件改的，所以这里把"注释格式"也当契约测：
    文件头必须以【类型】开头、必须有「适配设备」一节，且能对上所在目录。
    """
    from providers import packs
    from providers.packs import gamepad, headset, keyboard, mouse

    groups = (("mouse", mouse), ("keyboard", keyboard),
              ("headset", headset), ("gamepad", gamepad))
    seen: list[str] = []
    for name, group in groups:
        _check(f"{name} 目录有模块", len(group.MODULES) > 0)
        for module in group.MODULES:
            short = module.__name__.rsplit(".", 1)[-1]
            tag = f"{name}/{short}"
            doc = (module.__doc__ or "").strip()
            _check(f"{tag} 在 {name} 目录", f".{name}." in module.__name__)
            _check(f"{tag} 头部标了类型", doc.startswith("【"))
            _check(f"{tag} 写了适配设备", "适配设备" in doc)
            _check(f"{tag} 有 match", callable(getattr(module, "match", None)))
            _check(f"{tag} 有 probe", callable(getattr(module, "probe", None)))
            seen.append(module.__name__)

    expected = [m for _, group in groups for m in group.MODULES]
    _check("PACKS 与四类顺序一致", list(packs.PACKS) == expected)
    _check("没有重复登记", len(set(seen)) == len(seen))
    _check("共用模块不参与扫描",
           all("_compx" not in m.__name__ for m in packs.PACKS))


if __name__ == "__main__":
    test_compx()
    test_hidpp_version()
    test_hidpp10()
    test_razer()
    test_others()
    test_hyperx()
    test_brand_frames()
    test_descriptor()
    test_endpoints()
    test_merge()
    test_input_guard()
    test_packs_layout()
    print("ALL OK")
