# -*- coding: utf-8 -*-
"""用各品牌的只读电量帧模拟 2.4G 接收器，再跑真正的扫描。

不往系统里装驱动。hid 枚举和收发换成这批虚拟接收器，
扫描、去重、类型判断仍走 app 里的代码。对不上的帧不会被编造成电量。
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))


def _compx(level: int, charging: int = 0) -> bytes:
    frame = bytearray(17)
    frame[0] = 0x08
    frame[1] = 0x04
    frame[6] = level & 0xFF
    frame[7] = charging & 0xFF
    frame[16] = (0x55 - (sum(frame[:16]) & 0xFF)) & 0xFF
    return bytes(frame)


def _feature83(level: int, charging: int = 0) -> bytes:
    buf = bytearray(65)
    buf[6] = 0x83
    buf[7] = charging & 0xFF
    buf[8] = level & 0xFF
    return bytes(buf)


def _hidpp(req: bytes) -> bytes | None:
    if len(req) < 7 or req[0] not in (0x10, 0x11) or req[1] != 1:
        return None
    feat = req[2]
    func = req[3] >> 4
    params = bytes(req[4:])
    name = b"PRO X SUPERLIGHT"
    payload = None
    if feat == 0 and func == 0:
        fid = (params[0] << 8) | params[1]
        if fid == 0:
            payload = bytes((4, 2))
        else:
            payload = bytes(({0x0005: 0x05, 0x1004: 0x0E}.get(fid, 0),))
    elif feat == 0x05 and func == 0:
        payload = bytes((len(name),))
    elif feat == 0x05 and func == 1:
        payload = name + b"\x00"
    elif feat == 0x0E and func == 1:
        payload = bytes((64, 0, 0))
    if payload is None:
        return None
    size = 20 if req[0] == 0x11 else 7
    buf = bytearray(size)
    buf[0] = req[0]
    buf[1] = req[1]
    buf[2] = feat
    buf[3] = req[3]
    buf[4:4 + len(payload)] = payload[:size - 4]
    return bytes(buf)


def _evision(level: int) -> bytes:
    buf = bytearray(64)
    buf[0] = 0x04
    buf[3] = 0x1A
    buf[7] = 0x00
    buf[8] = level & 0xFF
    buf[9] = 0
    return bytes(buf)


def _razer(req: bytes) -> bytes:
    buf = bytearray(91)
    buf[1] = 0x02
    buf[7] = 0x07
    cmd = req[8] if len(req) > 8 else 0x80
    buf[8] = cmd
    buf[10] = 200 if cmd == 0x80 else 0
    return bytes(buf)


def _vaxee(req: bytes) -> bytes:
    cmd = req[4] if len(req) > 4 else 0
    buf = bytearray(64)
    buf[0] = 0x0E
    buf[4] = cmd
    buf[5] = 16 if cmd == 0x0B else 0
    return bytes(buf)


def _flydigi() -> bytes:
    buf = bytearray(16)
    buf[0] = 0x5A
    buf[1] = 0xA5
    buf[2] = 0x01
    buf[11] = 0x04  # 放电，4 档 = 80%
    return bytes(buf)


def _nordic54() -> bytes:
    return bytes((0x08, 0x72, 0x00, 0x0A, 0x00, 0x07, 0x01, 88, 0x10, 0x11))


def _hyperx(req: bytes) -> bytes | None:
    if len(req) >= 2 and req[0] == 0x66 and req[1] == 0x89:
        return bytes((0x66, 0x89, 0x0E, 0xD7, 48))
    if len(req) >= 2 and req[0] == 0x66 and req[1] == 0x8A:
        return bytes((0x66, 0x8A, 0x00))
    return None


def _steel(pid: int):
    """每只赛睿只回答自己那一种帧，避免耳机的 b0 被鼠标当成电量。"""
    def respond(req: bytes) -> bytes | None:
        if len(req) < 2:
            return None
        if pid == 0x22A1 and req[1] == 0xB0:
            return bytes((0xB0, 0x03, 76, 0x00))
        if pid == 0x1838 and req[1] == 0xD2:
            return bytes((0xD2, 0x40))
        return None
    return respond


# (名称, VID, PID, 页面, 用法, 期望电量, 期望类型, 应答)
# 应答: ("passive", frame) 打开就上报；("out", fn)；("feature", fn)；("none", None) 不该读到
def _evision_slow(level: int, delay: float = 3.0):
    """WOB 网页驱动那套：arg=6、校验和取和，回包还要等几秒（Rainy75 / Wave75）。"""

    def handle(request: bytes):
        if len(request) < 5 or request[0] != 0x04:
            return None
        if request[3] != 0x1A or request[4] != 0x06:
            return None
        total = (0x1A + 0x06) & 0xFFFF
        if request[1] != (total & 0xFF) or request[2] != (total >> 8):
            return None
        buf = bytearray(64)
        buf[0] = 0x04
        buf[3] = 0x1A
        buf[7] = 0x00
        buf[8] = level & 0xFF
        buf[9] = 0
        return ("delayed", delay, bytes(buf))

    return handle


def _out(fn):
    return ("out", fn)

def _feat(fn):
    return ("feature", fn)


DEVICES = [
    ("罗技 PRO X", 0x046D, 0xC547, 0xFF00, 0x0002, 64, "mouse", _out(_hidpp)),
    ("HyperX Cloud III", 0x03F0, 0x05B7, 0xFF13, 0x0001, 48, "headset", _out(_hyperx)),
    ("雷柏 VT9", 0x24AE, 0x1001, 0xFF01, 0x0001, 72, "mouse", ("passive", bytes((0xBB, 0xB0, 0, 0, 0, 0, 72)))),
    ("达尔优 A950", 0x260D, 0x1175, 0xFF02, 0x0002, 35, "mouse", _out(lambda _r: _compx(35))),
    ("Pulsar X2", 0x3554, 0xF508, 0xFF02, 0x0002, 41, "mouse", _out(lambda _r: _compx(41))),
    ("Attack Shark X11", 0x3554, 0xFB44, 0xFF02, 0x0002, 52, "mouse", _out(lambda _r: _compx(52))),
    ("仁魔 ES21", 0x3554, 0xA101, 0xFF02, 0x0002, 28, "mouse", _out(lambda _r: _compx(28))),
    ("Ninjutso Sora", 0x3554, 0xA102, 0xFF02, 0x0002, 33, "mouse", _out(lambda _r: _compx(33))),
    ("LunaFury", 0x3554, 0xA103, 0xFF02, 0x0002, 36, "mouse", _out(lambda _r: _compx(36))),
    ("WEIKAV 键盘", 0x3554, 0xA104, 0xFF02, 0x0002, 40, "keyboard", _out(lambda _r: _compx(40))),
    ("Finalmouse ULX", 0x3554, 0xA105, 0xFF02, 0x0002, 29, "mouse", _out(lambda _r: _compx(29))),
    ("赴极 OGM", 0x3554, 0xA106, 0xFF02, 0x0002, 45, "mouse", _out(lambda _r: _compx(45))),
    ("塞洛斯 V8", 0x3554, 0xA107, 0xFF02, 0x0002, 51, "mouse", _out(lambda _r: _compx(51))),
    ("因科特 G23", 0x3554, 0xA108, 0xFF02, 0x0002, 63, "mouse", _out(lambda _r: _compx(63))),
    ("狼途 G3", 0x3554, 0xA109, 0xFF02, 0x0002, 27, "mouse", _out(lambda _r: _compx(27))),
    ("EXX 鼠标", 0x3554, 0xA10A, 0xFF02, 0x0002, 39, "mouse", _out(lambda _r: _compx(39))),
    ("ZYNOO 鼠标", 0x3554, 0xA10B, 0xFF02, 0x0002, 42, "mouse", _out(lambda _r: _compx(42))),
    ("名龙星球", 0x3554, 0xA10C, 0xFF02, 0x0002, 57, "mouse", _out(lambda _r: _compx(57))),
    ("CRDRAKO", 0x3554, 0xA10D, 0xFF02, 0x0002, 66, "mouse", _out(lambda _r: _compx(66))),
    ("ROYUAN 鼠标", 0x3554, 0xA10E, 0xFF02, 0x0002, 31, "mouse", _out(lambda _r: _compx(31))),
    ("狼蛛 F75 键盘", 0x3554, 0xFA09, 0xFF02, 0x0002, 47, "keyboard", _out(lambda _r: _compx(47))),
    ("VXE R1", 0x3554, 0xF58A, 0xFF02, 0x0002, 46, "mouse", _out(lambda _r: _compx(46))),
    ("VGN Dragonfly", 0x3554, 0xF505, 0xFF02, 0x0002, 53, "mouse", _out(lambda _r: _compx(53))),
    ("Hitscan Hyperlight", 0x3770, 0x0200, 0xFF02, 0x0002, 75, "mouse", _out(lambda _r: _compx(75))),
    ("ATK Zero", 0x373B, 0x1155, 0xFF05, 0x0001, 88, "mouse", _out(lambda _r: _nordic54())),
    ("ATK V75X 键盘", 0x320F, 0x5088, 0xFF1C, 0x0092, 93, "keyboard", _out(lambda _r: _evision(93))),
    ("Rainy75 慢协议", 0x320F, 0x5091, 0xFF1C, 0x0092, 68, "keyboard", _out(_evision_slow(68))),
    ("万灵 Beast X", 0x36A7, 0xA880, 0xFFFF, 0x0000, 61, "mouse", _feat(lambda _r: _feature83(61))),
    ("兰族 Maya X", 0x373E, 0x001E, 0xFFFF, 0x0000, 31, "mouse", _feat(lambda _r: _feature83(31))),
    ("G-Wolves HTS", 0x33E4, 0x5803, 0xFFFF, 0x0000, 44, "mouse", _feat(lambda _r: _feature83(44))),
    ("迈从 A5", 0x2023, 0xF013, 0xFFFF, 0x0000, 22, "mouse", _feat(lambda _r: _feature83(22))),
    ("前行者 X87 键盘", 0x258A, 0x0101, 0xFFFF, 0x0000, 58, "keyboard", _feat(lambda _r: _feature83(58))),
    ("迈从 G7", 0xA8A5, 0x2255, 0xFF01, 0x0001, 60, "mouse",
     _out(lambda _r: bytes((0xAA, 0x30, 0xA5, 0x0B, 0x0A, 0x01, 0x01, 0x01, 60, 0)))),
    ("雷蛇 毒蝰", 0x1532, 0x007A, 0xFF01, 0x0001, 78, "mouse", _feat(_razer)),
    ("华硕 ROG 鼠标", 0x0B05, 0x1A72, 0xFF01, 0x0001, 53, "mouse",
     _out(lambda _r: bytes((0x00, 0x12, 0x07, 0, 0, 53, 0, 0, 0, 0, 0)))),
    ("VAXEE XE", 0x3057, 0x2001, 0xFF05, 0x0001, 80, "mouse", _feat(_vaxee)),
    ("怒喵 Infinity", 0x3151, 0x5007, 0xFF01, 0x0001, 55, "mouse",
     _out(lambda _r: bytes((0x05, 0x00, 0x00, 55)))),
    ("黑爵 AJ159", 0x3151, 0x4020, 0xFF01, 0x0001, 49, "mouse",
     _out(lambda _r: bytes((0x05, 0x00, 0x00, 49)))),
    ("Akko 鼠标", 0x3151, 0x4011, 0xFF01, 0x0001, 37, "mouse",
     _out(lambda _r: bytes((0x05, 0x00, 0x00, 37)))),
    ("赛睿 Arctis Nova 7", 0x1038, 0x22A1, 0xFFC0, 0x0001, 76, "headset", _out(_steel(0x22A1))),
    ("赛睿 Aerox 3", 0x1038, 0x1838, 0xFFC0, 0x0001, 64, "mouse", _out(_steel(0x1838))),
    ("JBL Quantum", 0x0ECB, 0x2088, 0xFF13, 0x0001, 90, "headset",
     ("passive", bytes((0x08, 90)))),
    ("飞智 Vader 5 Pro", 0x37D7, 0x2401, 0xFFA0, 0x0001, 80, "gamepad", _out(lambda _r: _flydigi())),
    ("八位堂 Pro 2", 0x2DC8, 0x6009, 0x0001, 0x0005, 72, "gamepad",
     ("passive", bytes((0x04,)) + bytes(13) + bytes((72,)))),
    ("索尼 DualSense", 0x054C, 0x0CE6, 0x0001, 0x0005, 70, "gamepad",
     ("passive", bytes((0x01,)) + bytes(52) + bytes((0x07,)))),
    # 没有对过的私有帧：扫描不该给出电量
    ("IPI Float", 0x372E, 0x1014, 0xFF12, 0x0001, None, "", ("none", None)),
    ("Lofree Hyzen", 0x388D, 0x0025, 0xFF12, 0x0001, None, "", ("none", None)),
    ("EPOS 耳机", 0x1395, 0x0001, 0xFF12, 0x0001, None, "", ("none", None)),
    ("任天堂 Pro", 0x057E, 0x2009, 0x0001, 0x0005, None, "", ("none", None)),
]


class _Handle:
    def __init__(self, spec):
        self.spec = spec
        self.queue: list[bytes] = []
        self.pending: list[tuple[float, bytes]] = []
        self.feature = b""
        kind, payload = spec
        if kind == "passive" and payload:
            self.queue.append(payload)

    def write(self, data: bytes) -> int:
        kind, fn = self.spec
        if kind == "out" and fn:
            reply = fn(data)
            if isinstance(reply, tuple) and reply and reply[0] == "delayed":
                # ("delayed", 秒, 帧)：WOB 那类接收器按 5 秒一班回包
                self.pending.append((time.monotonic() + reply[1], reply[2]))
            elif reply:
                self.queue.append(reply)
        return len(data)

    def read(self, size: int, timeout_ms: int = 0):
        now = time.monotonic()
        for item in list(self.pending):
            if item[0] <= now:
                self.pending.remove(item)
                self.queue.append(item[1])
        if not self.queue:
            return []
        return list(self.queue.pop(0)[:size])

    def send_feature_report(self, data: bytes) -> int:
        kind, fn = self.spec
        if kind == "feature" and fn:
            self.feature = fn(data) or b""
        return len(data)

    def get_feature_report(self, report_id: int, size: int):
        data = self.feature or bytes(size)
        return list(data[:size])


class _Device:
    def __init__(self):
        self._h: _Handle | None = None

    def open_path(self, path) -> None:
        self._h = _Handle(NODES[bytes(path)])

    def set_nonblocking(self, _flag) -> None:
        return None

    def write(self, data) -> int:
        return self._h.write(bytes(data)) if self._h else 0

    def read(self, size, timeout_ms=0):
        return self._h.read(size, timeout_ms) if self._h else []

    def send_feature_report(self, data) -> int:
        return self._h.send_feature_report(bytes(data)) if self._h else 0

    def get_feature_report(self, report_id, size):
        return self._h.get_feature_report(report_id, size) if self._h else []

    def close(self) -> None:
        self._h = None


def _path(vid: int, pid: int, token: str, col: str) -> bytes:
    # 真机上同一只接收器的两条集合只差最后的集合号。
    text = (f"\\\\?\\HID#VID_{vid:04X}&PID_{pid:04X}&MI_00#"
            f"7&{token}&0&{col}#{{4d1e55b2-f16f-11cf-88cb-001111000030}}")
    return text.encode("utf-8")


_STD = {
    "mouse": (0x0001, 0x0002),
    "keyboard": (0x0001, 0x0006),
    "headset": (0x000C, 0x0001),
    "gamepad": (0x0001, 0x0005),
}

NODES: dict[bytes, tuple] = {}
ENUM: list[dict] = []
for index, (name, vid, pid, page, usage, _level, kind, spec) in enumerate(DEVICES):
    token = f"sim{index:02d}"
    path = _path(vid, pid, token, "0000")
    NODES[path] = spec
    ENUM.append({
        "path": path,
        "vendor_id": vid,
        "product_id": pid,
        "usage_page": page,
        "usage": usage,
        "interface_number": 0,
        "product_string": name,
        "manufacturer_string": "SIM",
    })
    std = _STD.get(kind)
    if std and (page, usage) != std:
        extra = _path(vid, pid, token, "0001")
        NODES[extra] = ("none", None)
        ENUM.append({
            "path": extra,
            "vendor_id": vid,
            "product_id": pid,
            "usage_page": std[0],
            "usage": std[1],
            "interface_number": 0,
            "product_string": name,
            "manufacturer_string": "SIM",
        })


hid = types.ModuleType("hid")
hid.enumerate = lambda: [dict(item) for item in ENUM]
hid.device = _Device
sys.modules["hid"] = hid

from config import Config  # noqa: E402
from scanner import Scanner  # noqa: E402


def main() -> int:
    found, debug = Scanner(Config()).scan(with_debug=True, force=True)
    sim_ids = {f"{vid:04X}:{pid:04X}" for _n, vid, pid, *_rest in DEVICES}
    by_id: dict[str, list] = {}
    real = []
    for device in found:
        if device.vid_pid in sim_ids:
            by_id.setdefault(device.vid_pid, []).append(device)
        elif device.level is not None:
            real.append(device)

    failed = 0
    print(f"{'设备':<22} {'VID:PID':<11} {'电量':>6} {'类型':<10} {'通道'}")
    for name, vid, pid, _page, _use, level, kind, _spec in DEVICES:
        vid_pid = f"{vid:04X}:{pid:04X}"
        hits = by_id.get(vid_pid, [])
        if level is None:
            if hits:
                failed += 1
                got = ", ".join(f"{d.percent_text}%/{d.source}" for d in hits)
                print(f"{name:<22} {vid_pid:<11} 不该出现  实际 {got}")
            else:
                print(f"{name:<22} {vid_pid:<11} {'—':>6} {'—':<10} 无电量帧，未显示")
            continue
        ok = [d for d in hits if d.level is not None and int(round(d.level)) == level and d.kind == kind]
        if ok:
            d = ok[0]
            print(f"{name:<22} {vid_pid:<11} {d.percent_text:>5}% {d.kind:<10} {d.source}")
        else:
            failed += 1
            if not hits:
                print(f"{name:<22} {vid_pid:<11} 期望 {level}% {kind}  没有读到")
            else:
                got = ", ".join(
                    f"{d.percent_text}% {d.kind} {d.source}" for d in hits)
                print(f"{name:<22} {vid_pid:<11} 期望 {level}% {kind}  实际 {got}")

    if real:
        print("\n本机真实设备（不在这次模拟里）:")
        for device in real:
            print(f"  {device.name} {device.vid_pid} {device.percent_text}% {device.source}")

    print(f"\n模拟 {len(DEVICES)} 台，不一致 {failed} 台")
    if failed and debug:
        print("--- 调试 ---")
        for line in debug:
            if "异常" in line or "没有读到" in line:
                print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
