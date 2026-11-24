# -*- coding: utf-8 -*-
"""电量通道的唯一定义处：谁读、按什么顺序读、结果怎么排序。

以前这些规则散在三处 —— `scanner` 里一份通道列表、一份"厂商通道"前缀表、
一份保留时长表，再加一份评分逻辑。改一个通道要同时翻三个地方，漏一处就出现
"通道能读到但列表里被系统条目顶掉"这种怪现象。现在全部收在这里：

* `CHANNELS`：通道清单（顺序 = 合并时的优先级）；
* `SOURCE_RULES`：按来源前缀声明"是不是设备自己的协议、读不到时保留多久、加多少分"。

只做 2.4G 接收器与 USB 有线，蓝牙链路在任何通道都不参与。
只留逐型号/按芯片方案验证过的协议实现，不设"什么都能试一遍"的兜底扫描。

注意文件顺序：纯数据与判定函数在前，通道模块的导入在后 ——
避免 `added` 反查注册表时撞成循环导入。
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
# 表里只列真正会产出读数的来源 —— 全部是设备自己的电量协议。
SOURCE_RULES: tuple[SourceRule, ...] = (
    # 罗技闲置约 15 分钟进深度休眠，保留 10 分钟才不会让设备"凭空消失"
    SourceRule("HID++", vendor=True, keep=600.0, bonus=1),
    SourceRule("Evision", vendor=True, keep=300.0, bonus=1),
    SourceRule("协议包", vendor=True, keep=300.0, bonus=1),
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
    # 「添加设备」写进来的外置协议，与厂商通道同等权重
    SourceRule("已添加", vendor=True, keep=300.0, bonus=1),
)

# 这些 VID 已经有专用通道在读（Evision 认 320F 的接收器），
# 「添加设备」写进来的外置协议不再重复试，否则同一只接收器会被两套代码各读一遍。
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


# 通道的统一签名：(debug 列表或 None, 是否手动刷新) -> 设备列表
Scan = Callable[[list | None, bool], list[Device]]


@dataclass(frozen=True)
class Channel:
    key: str          # 内部名，日志与去重时用
    label: str        # 诊断页显示名
    run: Scan
    note: str = ""    # 一句话说明这条通道读什么


def _channels() -> tuple[Channel, ...]:
    """通道清单。函数内导入：让上面的常量先就位，避免与 added 循环导入。"""
    from providers import added, evision, hidpp, hyperx, oem, packs

    # 五条专用协议通道 + 一条「添加设备」的外置协议通道。
    # 同一台设备被两条通道读到时，`scanner` 按 score() 保留一条。
    return (
        Channel("packs", "协议包",
                lambda d, f: packs.scan(d, force=f),
                "逐型号私有协议（2.4G 接收器与 USB 有线）"),
        Channel("evision", "Evision",
                lambda d, f: evision.scan_evision(d, force=f),
                "Evision/Compx 芯片方案的 2.4G 接收器"),
        Channel("hidpp", "HID++",
                lambda d, f: hidpp.scan_logitech(d, force=f),
                "罗技 Bolt / Unifying 接收器"),
        Channel("hyperx", "HyperX",
                lambda d, f: hyperx.scan_hyperx(d, force=f),
                "HyperX 2.4G 耳机"),
        Channel("oem", "芯片组",
                lambda d, f: oem.scan_oem(d, force=f),
                "按芯片方案读，覆盖一批贴牌"),
        Channel("added", "已添加",
                lambda d, f: added.scan_added(d, force=f),
                "「添加设备」里手动试读通过的协议"),
    )


CHANNELS: tuple[Channel, ...] = _channels()
