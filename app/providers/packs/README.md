# 协议包（packs）—— 想加一台新设备，从这里开始

这个目录按 **设备类型 → 品牌 → 型号** 三级组织。一台设备读不到电量，先看它属于哪一类，
再进对应目录找一个同品牌的文件照着写。

```
packs/
  base.py              公共底座：开句柄、读写、等待、冷却、报告长度
  mouse/               鼠标
    inphic_delux.py      1D57:FA65  英菲克 ZHEN / DELUX M900 Pro
    hecate.py            35BB:D00B  HECATE G5M Pro
    rapoo.py             24AE       雷柏 VT3 二代
    aula.py              38A6:28FD  狼蛛 L9 Ultra
    pulsar.py            3554       派世 X2 V2
    lingbao.py           3151:402D  凌豹 M5PRO Max
    thunderobot.py       369B:0234  雷神 ML903 NearLink Se
    eweadn.py            372E:1026  前行者 S9
    razer.py             1532       毒蝰 V4 Pro / Viper V3 Pro SE
    mchose.py            3837       A5 V2 Ultra / G3 V2 / 鼠标 V2 系列
    vgn.py               391D/3554  蜻蜓 F1 V5 Turbo+ / 蜻蜓 F2 大师+
    atk.py               373B       VXE R1 Nearlink / ATK 8K、F1 Ultimate、A9 Air
  keyboard/            键盘
    _compx.py            ——         3554:FA09 会话协议，三家键盘共用（不是独立链路）
    aula.py              3554/372E  F99 Pro / HERO 68 Air
    cherry.py            046A       PIXIU75
    ajazz.py             3151:4011  AK870
    lingbao.py           3554:FA09  K98
    eweadn.py            0C45:FEFE  X87
    asus.py              0B05:1ACE  ROG Strix Scope II 96 Wireless
    mchose.py            3837       V1 系列 / K7 V2 Ultra+ / G75 / QHW 新代 dongle
    vgn.py               320F:5088  V98 Pro
    atk.py               373B       VIA 通道键盘
    ganss.py             05AC:024F  GS3104T-Pro / 狼蛛 F108 Pro
  headset/             耳机
    hyperx_cf2.py        03F0:0AC1  Cloud Flight 2
    aula.py              38A6:0030  狼蛛 G9
    darkrim.py           3654:6901  寸渊影弑 SHADOW
    asus.py              0B05:1AFA  ROG 无线耳机
    razer.py             1532       BlackShark V2 Pro 2023 / Kraken V4
    mchose.py            291D/3837  V9 Pro / X9
    akg.py               0ECB:20D9  N9 Hybrid
    sony.py              054C:0FA8  INZONE H9 II
  gamepad/             手柄
    gamesir.py           3537       G7 Pro
    betop.py             20BC/20DD  北通 T9 / 鲲鹏 20、70
    haute.py             054C:0CE6  Haute42 Adapter 4DS
    mojhon.py            E2B7:122C  墨将 烈风2 GALE2
```

**一个品牌跨类型时会出现同名文件**：`mouse/vgn.py` 与 `keyboard/vgn.py` 是两个独立模块，
各管各的链路。谁先谁后由各目录 `__init__.py` 的 `MODULES` 顺序决定。

---

## 加一台新设备的三个步骤

### 1. 先确认它归哪一类

不知道的话，看设备在系统里的名称与接口形态：带 0xFF60/0x0061 且输入输出 20~33 字节的多是键盘；
带 0xFF02 且 17 字节的多是游戏鼠标；耳机常见 0xFF90 / 0xFFA0 这类厂商页且多为被动上报。

### 2. 在对应目录新建 `品牌.py`

文件名用品牌英文小写（`mchose.py`、`thunderobot.py`）。一个文件只管这个品牌在**这一类**下的
所有型号，不需要一个型号一个文件。

文件头部必须写清四件事，照着现有文件抄格式即可：

```python
# -*- coding: utf-8 -*-
"""【鼠标】品牌 型号A、型号B

适配设备
    型号A      VID:PID，哪个接口
    型号B      同上

怎么认
    判据是什么（接口页/用途、报文长度、feature 长度、产品名）

怎么读
    发什么帧、校验怎么算、电量在第几字节、充电位在第几字节

注意
    读到什么值要丢弃、有没有必须归还的状态（如远程模式）
"""
```

### 3. 实现 `match` 与 `probe`，登记到 `__init__.py`

```python
from __future__ import annotations

from providers.packs import base
from providers.packs.base import Ctx, Reading

VID = 0x1234
PID = 0x5678
PAGE = 0xFF00
USAGE = 0x0001
LEVEL_INDEX = 6
CHARGE_INDEX = 7


def match(ctx: Ctx) -> bool:
    """只看接口指纹，不做 I/O。判据越严越好：宁可读不到，也别认错设备。"""
    if ctx.vid != VID or ctx.pid != PID:
        return False
    return bool(ctx.pick(page_=PAGE, usage_=USAGE))


def build_query(length: int) -> bytes:
    frame = bytearray(max(length, 8))
    frame[0] = 0x02
    frame[1] = 0x81
    return bytes(frame)


def parse(raw: bytes):
    """一帧 → (电量, 是否充电)；解析不了就返回 None，绝不猜。"""
    for off in (0, 1):                      # report ID 可能被 hidapi 剥掉
        if len(raw) < off + CHARGE_INDEX + 1:
            continue
        if raw[off] != 0x02 or raw[off + 1] != 0x81:
            continue
        percent = raw[off + LEVEL_INDEX]
        if percent == 0 or percent > 100:    # 0 是休眠占位，不是电量
            return None
        return percent, raw[off + CHARGE_INDEX] != 0
    return None


def probe(ctx: Ctx, force: bool = False) -> Reading | None:
    targets = ctx.pick(page_=PAGE, usage_=USAGE)
    if not targets:
        return None
    key = ("mybrand", ctx.phys)
    if base.cooled(key, force):              # 冷却期内不再碰它，设备休眠是常态
        return None
    for member in targets[:2]:
        dev = None
        try:
            dev = base.open_member(member)
            base.drain(dev)                  # 丢掉上一轮残留的帧
            if not base.write(dev, build_query(base.io_lengths(member)[1])):
                continue
            hit = base.wait_for(dev, parse, ms=900)
            if hit is None:
                continue
            base.clear_fail(key)
            return Reading(hit[0], hit[1], label="协议包·我的品牌",
                           model="我的型号", kind=base.MOUSE)
        except Exception:
            continue
        finally:
            base.close(dev)                  # 句柄一定要关，不然下次打不开
    base.mark_fail(key)
    return None
```

然后在同目录 `__init__.py` 的 `MODULES` 里加一行。**被动听（不写设备）的排前面，
要发多条帧的排后面** —— 顺序就是优先级。

跑一遍自测：

```bash
python tools/test_packs.py     # 喂真机报文向量，不碰硬件
python tools/smoke.py          # 离屏构窗口 + 真实扫一遍
```

---

## 四条硬规矩（违反过就会出事）

1. **只发有出处的帧。** 查询帧必须来自官方软件抓包或公开逆向文档。猜出来的字节发出去，
   轻则读不到，重则把接收器状态机搅乱、鼠标掉线。
2. **能被动听就不写。** 设备会自发推状态帧的（雷柏、HyperX CF2、狼蛛 G9、英菲克），
   只在被动流里等。主动查询会打断它自己的上报节奏。
3. **失败不重试、不换命令。** 一轮最多一条查询帧，读不到就 `mark_fail` 冷却 150 秒。
   狂试只会让设备更叫不醒。
4. **发帧前先让位。** `base.write()` 会先确认系统空闲 0.6 秒，等不到就不发、返回 False，
   `mark_fail` 也会跳过（让位不是设备故障）。不要绕过它直接调 `dev.write()` ——
   键盘的厂商命令和按键报文共用一条链路，打字中途插帧会让用户觉得"按下去没反应"。

还有一条底线：**读不出确切百分比就不列出该设备**，不显示 `--`，也不猜一个值。

---

## 认设备常用的判据

| 判据 | 怎么拿 |
|---|---|
| 接口页 / 用途 | `base.page(m)` / `base.usage(m)` |
| 输入输出报告长度 | `base.io_lengths(m)` → (in_max, out_max) |
| feature 报告长度 | `base.feature_length(m)` |
| 某个 report ID 是否存在 | `base.out_reports(m)` → {id: 长度} |
| 接口路径里的集合编号 | `base.path_text(m)`，如 `&mi_03&col02#` |
| 产品名 | `base.product(m)` 或 `ctx.name` |

同一颗芯片的键盘与鼠标往往只差报告长度（20/20 对 17/17），所以**长度要写精确相等**，
不要写"大于等于"，否则会把同号段的另一种设备灌进这条通道。

几处必须按产品名让位的地方，注释里都写了原因：

- `keyboard/vgn.py`：320F:5088 上 V98 Pro 与 VXE75 同指纹，VXE75 要让给 Evision 通道
- `keyboard/ganss.py`：05AC:024F 上 GANSS 与狼蛛 F108 Pro 同指纹
- `keyboard/mchose.py`：3554:FA09 上迈从 G75、AULA F99、凌豹 K98 三家共用，靠会话型号密码分流

---

## 不在这个目录里的读取方式

有些设备不按型号适配，而是按**芯片方案**或**系统接口**读，它们在 `providers/` 上一层：

| 文件 | 适用 |
|---|---|
| `evision.py` | Evision / Compx 芯片方案的接收器 |
| `hidpp.py` | 罗技 Bolt / Unifying 接收器 |
| `hyperx.py` | HyperX 2.4G 耳机（老链路） |
| `oem.py` | 按芯片方案覆盖一批贴牌，不看 VID |
| `added.py` | 「添加设备」试读通过后写进来的外置协议 |

这些通道不区分设备类型 —— 一只接收器可能同时接键盘和鼠标，拆开反而读不全。
