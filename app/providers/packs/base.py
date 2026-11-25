# -*- coding: utf-8 -*-
"""协议包的公共底座：分组、开句柄、读写、冷却。

协议包按设备类型分四个目录（mouse / keyboard / headset / gamepad），
每个目录下再按品牌分文件，一个文件管这个品牌在该类型下的全部型号。
新增一台设备的完整步骤见 `packs/README.md`。

设计口径照搬参考项目（vigil-watt）的三条硬规矩，它们是用两次真实事故换来的：
1. **只发有出处的帧**。每个家族模块里的查询帧都是从官方软件抓包或公开逆向
   文档来的；这里不提供任何"枚举/扫描/猜字节"的能力。
2. **能被动听就不写**。会被动推状态帧的设备，只在被动流里等，不发帧。
3. **失败不重试、不换命令**。一轮最多一条查询帧，读不到就记一次失败，
   冷却一段时间再试——设备休眠是常态，狂试只会把 dongle 的状态机搅乱。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

try:
    import hid
except Exception:      # pragma: no cover
    hid = None

from model import GAMEPAD, HEADSET, KEYBOARD, MOUSE, UNKNOWN, Device
from providers.hidpath import phys_token
from providers.inputidle import wait_idle

# 同一只设备探测失败后，多久之内不再碰它。手动刷新（force）会绕过。
COOLDOWN = 150.0
_FAIL: dict[tuple, float] = {}

DEFAULT_READ = 64

# 发帧前让位等多久。协议包整轮预算只有 9 秒，这里不能等太久：
# 用户一直在打字时应当尽快放弃，而不是把预算耗在等待上。
WRITE_IDLE_LIMIT = 0.8

# 这一轮是不是"因为用户在输入而没发帧"。让位不算失败，
# 不能进冷却 —— 否则用户打一会儿字，设备就被关 150 秒。
_local = threading.local()


def deferred() -> bool:
    return bool(getattr(_local, "deferred", False))


def cooled(key: tuple, force: bool) -> bool:
    return (not force) and time.monotonic() < _FAIL.get(key, 0.0)


def mark_fail(key: tuple, seconds: float = COOLDOWN) -> None:
    if deferred():
        return                         # 让位不是设备的错
    _FAIL[key] = time.monotonic() + seconds


def clear_fail(key: tuple) -> None:
    _FAIL.pop(key, None)


# ---------------- 接口信息 ----------------
def page(m: dict) -> int:
    return m.get("usage_page") or 0


def usage(m: dict) -> int:
    return m.get("usage") or 0


def product(m: dict) -> str:
    return (m.get("product_string") or "").strip()


def path_text(m: dict) -> str:
    raw = m.get("path")
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "ignore")
    return str(raw or "")


# 报告长度是"认设备"最常用的判据：同一颗芯片的键盘/鼠标往往只差
# 输入输出的字节数。描述符按路径缓存在 hidreports 里，重复调用不重新解析。
def io_lengths(m: dict) -> tuple[int, int]:
    """该接口最长输入 / 输出报告的长度。读不到描述符时返回 (0, 0)。"""
    from providers import hidreports
    try:
        reports = hidreports.reports(m.get("path"))
    except Exception:
        return 0, 0
    return (max(reports.get("in", {}).values(), default=0),
            max(reports.get("out", {}).values(), default=0))


def out_reports(m: dict) -> dict[int, int]:
    """该接口的输出 report ID → 总长度。认"某个 ID 存不存在"时用。"""
    from providers import hidreports
    try:
        return hidreports.reports(m.get("path")).get("out", {})
    except Exception:
        return {}


def feature_length(m: dict) -> int:
    """该接口最长 feature 报告的长度；没有 feature 端点时为 0。"""
    from providers import hidreports
    try:
        feats = hidreports.reports(m.get("path")).get("feat", {})
    except Exception:
        return 0
    return max(feats.values()) if feats else 0


@dataclass
class Ctx:
    """一只接收器（或一台有线设备）下的全部 HID 集合。"""

    vid: int
    pid: int
    phys: str
    members: list[dict] = field(default_factory=list)
    name: str = ""

    @property
    def vid_pid(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    def pick(self, page_: int | None = None, usage_: int | None = None,
             path_has: str | None = None) -> list[dict]:
        out = []
        for m in self.members:
            if page_ is not None and page(m) != page_:
                continue
            if usage_ is not None and usage(m) != usage_:
                continue
            if path_has is not None and path_has.lower() not in path_text(m).lower():
                continue
            out.append(m)
        return out


@dataclass
class Reading:
    percent: float | None
    charging: bool | None = None      # None = 这一帧没带充电位
    label: str = ""                   # 通道名前缀（品牌）
    model: str = ""                   # 型号名，空则用产品名
    kind: str = UNKNOWN
    transport: str = "2.4G 接收器"


# ---------------- 句柄 ----------------
def open_member(m: dict):
    if hid is None:
        return None
    dev = hid.device()
    dev.open_path(m.get("path"))
    try:
        dev.set_nonblocking(False)    # read(size, timeout) 需要阻塞模式
    except Exception:
        pass
    return dev


def close(dev) -> None:
    try:
        if dev is not None:
            dev.close()
    except Exception:
        pass


def read(dev, ms: int = 120, size: int = DEFAULT_READ):
    """读一帧；超时返回 None。异常一律当无数据。"""
    try:
        raw = dev.read(size, max(1, int(ms)))
    except Exception:
        return None
    return bytes(raw) if raw else None


def drain(dev, limit: int = 8, ms: int = 1) -> None:
    for _ in range(limit):
        if read(dev, ms) is None:
            return


def write(dev, frame: bytes) -> bool:
    """发一帧。发之前先让位：用户正在连续输入时不发，返回 False。

    2.4G 键盘的厂商命令和按键报文共用一条空中链路与中断通道，打字中途
    插一帧会把 key-up 挤到命令往返之后，用户就会觉得"按下去没反应"。
    这里宁可这一轮不读，也不打断输入；调用方的 mark_fail 会自动跳过，
    不把让位算成失败。
    """
    _local.deferred = False
    if not wait_idle(limit=WRITE_IDLE_LIMIT):
        _local.deferred = True
        return False
    try:
        dev.write(bytes(frame))
        return True
    except Exception:
        return False


def wait_for(dev, parse, ms: int = 800, size: int = DEFAULT_READ):
    """在窗口内等一帧能解析的报文。parse(raw) -> 结果 or None。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        raw = read(dev, 100, size)
        if raw is None:
            continue
        hit = parse(raw)
        if hit is not None:
            return hit
    return None


def feature_roundtrip(dev, report_id: int, payload: bytes, size: int,
                      wait_ms: int = 20):
    """SetFeature(查询) → 等一小会 → GetFeature(同 ID)。

    设备普遍要 10~100ms 才把新状态写进 feature 缓冲，读太早会拿到上一条。
    """
    try:
        dev.send_feature_report(bytes([report_id]) + bytes(payload))
    except Exception:
        return None
    time.sleep(max(0, wait_ms) / 1000.0)
    try:
        raw = dev.get_feature_report(report_id, size)
    except Exception:
        return None
    return bytes(raw) if raw else None


def feature_get(dev, report_id: int, size: int):
    try:
        raw = dev.get_feature_report(report_id, size)
    except Exception:
        return None
    return bytes(raw) if raw else None


# ---------------- 结果 ----------------
_KIND_WORDS = (
    (HEADSET, ("headset", "headphone", "earbud", "耳机", "耳麦", "kraken",
               "blackshark", "arctis")),
    (GAMEPAD, ("controller", "gamepad", "joystick", "手柄", "dualsense", "gamesir")),
    (MOUSE, ("mouse", "鼠标", "x2 v2", "viper", "m900")),
    (KEYBOARD, ("keyboard", "键盘", "scope", "pixiu", "x87", "ak870")),
)


def guess_kind(ctx: Ctx, default: str = UNKNOWN) -> str:
    low = (ctx.name or "").lower()
    for kind, words in _KIND_WORDS:
        if any(word in low for word in words):
            return kind
    usages = {(page(m), usage(m)) for m in ctx.members}
    if (0x0001, 0x0005) in usages:
        return GAMEPAD
    if (0x0001, 0x0002) in usages:
        return MOUSE
    if (0x0001, 0x0006) in usages:
        return KEYBOARD
    return default


def emit(ctx: Ctx, reading: Reading, default_kind: str = UNKNOWN) -> Device:
    name = reading.model or ctx.name or f"无线设备 {ctx.vid_pid}"
    return Device(
        key=f"pack:{reading.label}:{ctx.vid:04x}:{ctx.pid:04x}:{ctx.phys}",
        name=name,
        kind=reading.kind if reading.kind != UNKNOWN else guess_kind(ctx, default_kind),
        level=reading.percent,
        charging=bool(reading.charging) if reading.charging is not None else False,
        source=reading.label,
        transport=reading.transport,
        raw={"phys": ctx.phys, "state": "正常"},
        vid_pid=ctx.vid_pid,
    )


__all__ = [
    "Ctx", "Reading", "cooled", "mark_fail", "clear_fail", "page", "usage",
    "product", "path_text", "io_lengths", "out_reports", "feature_length",
    "open_member", "close", "read", "drain", "write",
    "wait_for", "feature_roundtrip", "feature_get", "guess_kind", "emit",
    "phys_token",
]
