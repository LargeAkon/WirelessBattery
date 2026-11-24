# -*- coding: utf-8 -*-
"""电量通道的唯一定义处：谁读、按什么顺序读、结果怎么排序。

以前这些规则散在三处 —— `scanner` 里一份通道列表、一份"厂商通道"前缀表、
一份保留时长表，再加一份评分逻辑。改一个通道要同时翻三个地方，漏一处就出现
"通道能读到但列表里被系统条目顶掉"这种怪现象。现在全部收在这里：

* `CHANNELS`：通道清单（顺序 = 合并时的优先级）；
* `SOURCE_RULES`：按来源前缀声明"是不是设备自己的协议、读不到时保留多久、加多少分"。

只做 2.4G 接收器与 USB 有线，蓝牙链路在任何通道都不参与。

注意文件顺序：纯数据与判定函数在前，通道模块的导入在后 ——
`generic` 要用 `LIBRARY_SKIP_VIDS`，先定义再导入才不会撞成循环导入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from model import UNKNOWN, Device


@dataclass(frozen=True)
class SourceRule:
    """一条来源前缀的判定规则。"""
    prefix: str
    vendor: bool = False   # 是否"设备自己的电量协议"：是的话系统条目要让位
    keep: float = 180.0    # 读不到时，上次读数保留多久（秒）
    bonus: int = 0         # 合并去重时的加分


# 前缀越长越先匹配（"协议包·雷蛇" 与 "协议包" 都归到 "协议包" 那条）。
SOURCE_RULES: tuple[SourceRule, ...] = (
    # 罗技闲置约 15 分钟进深度休眠，保留 10 分钟才不会让设备"凭空消失"
    SourceRule("HID++", vendor=True, keep=600.0, bonus=1),
    SourceRule("Evision", vendor=True, keep=300.0, bonus=1),
    SourceRule("协议包", vendor=True, keep=300.0, bonus=1),
    SourceRule("协议库", vendor=True, keep=300.0, bonus=1),
    SourceRule("HyperX", vendor=True, keep=300.0, bonus=1),
    # 芯片组通道的十三个子链路共用一组前缀，保留时长一致
    SourceRule("Compx", vendor=True, keep=300.0, bonus=1),
    SourceRule("厂商", vendor=True, keep=300.0, bonus=1),
    SourceRule("Razer", vendor=True, keep=300.0, bonus=1),
    SourceRule("华硕", vendor=True, keep=300.0, bonus=1),
    SourceRule("雷柏", vendor=True, keep=300.0, bonus=1),
    SourceRule("VAXEE", vendor=True, keep=300.0, bonus=1),
    SourceRule("迈从", vendor=True, keep=300.0, bonus=1),
    SourceRule("Nordic54", vendor=True, keep=300.0, bonus=1),
    SourceRule("赛睿", vendor=True, keep=300.0, bonus=1),
    SourceRule("JBL", vendor=True, keep=300.0, bonus=1),
    SourceRule("飞智", vendor=True, keep=300.0, bonus=1),
    SourceRule("怒喵", vendor=True, keep=300.0, bonus=1),
    SourceRule("索尼", vendor=True, keep=300.0, bonus=1),
    SourceRule("8BitDo", vendor=True, keep=300.0, bonus=1),
    # HID 标准电池集合 / 手柄：走系统与标准报告，保留时长短一些
    SourceRule("HID 电量", vendor=True, keep=180.0, bonus=1),
    SourceRule("手柄电量", vendor=True, keep=180.0, bonus=1),
    SourceRule("系统电池", keep=180.0),
    SourceRule("系统设备电量", keep=180.0),
    SourceRule("自定义报文规则", keep=180.0),
)

# 这些 VID 已经有专用通道在读（Evision 认 320F 的接收器），协议库不再重复试，
# 否则同一只接收器会被两套代码各读一遍，出现两行同名设备。
LIBRARY_SKIP_VIDS = frozenset({0x320F})

_DEFAULT_RULE = SourceRule("")


def rule_for(source: str | None) -> SourceRule:
    text = source or ""
    best: SourceRule | None = None
    for rule in SOURCE_RULES:
        if text.startswith(rule.prefix) and (best is None or len(rule.prefix) > len(best.prefix)):
            best = rule
    return best or _DEFAULT_RULE


def is_vendor(device: Device) -> bool:
    """这条读数是不是设备自己的电量协议给的。"""
    return rule_for(device.source).vendor


def keep_seconds(device: Device) -> float:
    """读不到时保留上次读数多久。"""
    return rule_for(device.source).keep


def score(device: Device) -> int:
    """同一台设备出现多条读数时，谁更值得留。"""
    value = 0
    if device.level is not None:
        value += 4
    if device.kind != UNKNOWN:
        value += 2
    rule = rule_for(device.source)
    if rule.vendor:
        value += 2
    value += rule.bonus
    # 同一只鼠标可能同时被"有线直连"和"接收器"看到（插着线充电、无线也还注册着）。
    # 有线这一路是实时直连，接收器那路可能滞后，合并时优先保留有线读数。
    if (device.transport or "").startswith("USB 有线"):
        value += 3
    if device.name and any(ch.isupper() for ch in device.name):
        value += 1
    return value


# 通道的统一签名：(debug 列表或 None, 是否手动刷新, 自定义规则) -> 设备列表
Scan = Callable[[list | None, bool, list], list[Device]]


@dataclass(frozen=True)
class Channel:
    key: str          # 内部名，日志与去重时用
    label: str        # 诊断页显示名
    run: Scan
    note: str = ""    # 一句话说明这条通道读什么


def _channels() -> tuple[Channel, ...]:
    """通道清单。函数内导入：让上面的常量先就位，避免与 generic 循环导入。"""
    from providers import (evision, generic, hid_desc, hidpp, hyperx, oem,
                           packs, raw_hid, win_battery, win_pnp, xinput_pad)

    # 顺序即优先级：已验证的私有协议排在前面，兜底通道垫后。
    # 同一台设备被多条通道读到时，`scanner` 会按 score() 保留一条。
    return (
        Channel("packs", "协议包",
                lambda d, f, r: packs.scan(d, force=f),
                "逐型号私有协议（2.4G 接收器与 USB 有线）"),
        Channel("evision", "Evision",
                lambda d, f, r: evision.scan_evision(d, force=f),
                "Evision/Compx 芯片方案的 2.4G 接收器"),
        Channel("hidpp", "HID++",
                lambda d, f, r: hidpp.scan_logitech(d, force=f),
                "罗技 Bolt / Unifying 接收器"),
        Channel("hyperx", "HyperX",
                lambda d, f, r: hyperx.scan_hyperx(d, force=f),
                "HyperX 2.4G 耳机"),
        Channel("oem", "芯片组",
                lambda d, f, r: oem.scan_oem(d, force=f),
                "按芯片方案读，覆盖一批贴牌"),
        Channel("library", "协议库",
                lambda d, f, r: generic.scan_profiles(d, force=f),
                "按 VID:PID 精确匹配已知型号"),
        Channel("hid_desc", "HID电量",
                lambda d, f, r: hid_desc.scan_hid_battery(d),
                "描述符里带 Battery Strength 的设备"),
        Channel("xinput", "手柄",
                lambda d, f, r: xinput_pad.scan_xinput(d),
                "XInput 手柄（四档电量）"),
        Channel("win_battery", "系统电池",
                lambda d, f, r: win_battery.scan_win_battery(d),
                "系统电池类设备"),
        Channel("win_pnp", "系统电量",
                lambda d, f, r: win_pnp.scan_windows_battery(d),
                "设备属性里的 BatteryLevel"),
        Channel("raw_hid", "自定义规则",
                lambda d, f, r: raw_hid.scan_custom(r, d),
                "诊断时录下来的私有报文规则"),
    )


CHANNELS: tuple[Channel, ...] = _channels()
