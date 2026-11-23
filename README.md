<div align="center">

<h1>外设电量 · WirelessBattery</h1>

<p>Windows 托盘小工具：一屏看完 <b>2.4G 无线键盘、鼠标、手柄、耳机</b> 的电量。</p>

<p>
<img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=flat-square&logo=windows11&logoColor=white" alt="Windows">
<img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square" alt="License">
<img src="https://img.shields.io/github/v/release/LargeAkon/WirelessBattery?style=flat-square&label=release&color=0A0B0C" alt="release">
<img src="https://img.shields.io/github/downloads/LargeAkon/WirelessBattery/total?style=flat-square&label=downloads" alt="downloads">
</p>

<p>
<a href="https://github.com/LargeAkon/WirelessBattery/releases/latest"><img src="https://img.shields.io/badge/%E4%B8%8B%E8%BD%BD-WirelessBatterySetup.exe-2ea44f?style=for-the-badge&logo=windows&logoColor=white" alt="Download"></a>
</p>

<p>
<a href="#界面">界面</a> ·
<a href="#支持设备">支持设备</a> ·
<a href="#安装">安装</a> ·
<a href="#使用">使用</a> ·
<a href="#适配新设备">适配新设备</a> ·
<a href="#开发">开发</a>
</p>

</div>

---

## 界面

<div align="center">
  <img src="docs/tray.png" width="760" alt="托盘图标各电量档位">
  <br><sub>托盘图标：电池内腔填多长，就是还剩多少电；充电时绿色从左往右涨满</sub>
</div>

<div align="center">
  <img src="docs/card-light.png" width="380" alt="设备卡片 · 浅色主题">
  <img src="docs/card.png" width="380" alt="设备卡片 · 深色主题">
  <br><sub>设备卡片：左键点托盘图标弹出，所有在线设备一屏看完</sub>
</div>

<div align="center">
  <img src="docs/diag.png" width="720" alt="设备诊断窗口">
  <br><sub>设备诊断：列出全部 HID 端点并标注用途，★ 那行才是承载电量的协议通道</sub>
</div>

---

## 功能

| 能力 | 说明 |
|---|---|
| **托盘读数** | 电池图标内腔的填充长度跟着电量走，插电时逐帧涨满，不点开也能看见 |
| **多设备同屏** | 键鼠、手柄、耳机同时列出，各自独立电量条，标注连接方式 |
| **休眠不丢** | 设备断连时保留上次读数并标「信号中断」，不会一闪一闪地跳没 |
| **刷新策略** | 常规 10 / 15 / 20 分钟；检测到充电自动加密到 30 秒 |
| **设备诊断** | 端点列表 + 复制识别 + 导出报告，读不到的设备靠它定位原因 |
| **开机自启** | 写 HKCU 注册表，无需管理员权限，卸载时自动清理 |

---

## 支持设备

2.4G 没有统一的电量标准——蓝牙有 GATT 电池服务，2.4G 各家一份私有报文。
所以这里不读「通用接口」，而是**按无线方案商逐个实现协议**：品牌几百个，方案商只有十来家。

| 方案商 / 通道 | 覆盖 |
|---|---|
| **HID++ 2.0** | 罗技全系：G Pro、GPW、MX Master、G913 等 |
| **Evision** | ATK、VGN、VXE 的键盘与部分鼠标（`VID 320F`，`FF1C:0092`） |
| **Compx 17 字节帧** | 页面 `FF02` 的接收器，不看品牌：ATK、VXE、VGN 鼠标、达尔优、Pulsar、Attack Shark、狼蛛键盘、Ninjutso、因科特、Hitscan、塞洛斯、Finalmouse、赴极等贴牌 |
| **Nordic 54** | ATK Zero 一类（`VID 373B`，页面 `FF05`） |
| **0x83 特征报告** | 万灵花兽、兰族、G-Wolves、迈从；中颖公版上的狼蛛、前行者、部分黑爵与多彩 |
| **迈从 G7** | `VID A8A5` 的 `AA 30` 应答 |
| **Razer** | 雷蛇（`0x07` / `0x80` 查询帧） |
| **ASUS** | 华硕 ROG / TUF（`12 07` / `12 01`） |
| **VAXEE** | VAXEE 无线鼠标 |
| **怒喵 / 黑爵 / Akko** | 同一套状态报告 `0x05`（`VID 3151`） |
| **赛睿** | Arctis Nova 7 Gen2 的 `b0`、Aerox 的 `d2`、Rival 3 的 `aa` |
| **飞智** | Vader 5 Pro 的 GET_INFO（`VID 37D7`）；旧款多数只有 XInput 四档 |
| **HyperX** | HyperX 2.4G 耳机（按产品号匹配） |
| **雷柏 / JBL** | 接收器主动上报，被动监听 |
| **八位堂 / 索尼** | DualSense、DualShock 与八位堂手柄的输入报告 |
| **HID 标准电池集合** | 描述符里带 Battery Strength 的设备：西伯利亚、iKF、阿斯盾、漫步者 HECATE 等 |
| **XInput** | Xbox 手柄，以及走 XInput 的飞智、LEADJOY（四档电量） |
| **Windows 电池类 / 设备属性** | 系统为其注册了电池设备或能报告 BatteryLevel 的外设 |
| **自定义规则** | 你在诊断窗口里现场识别出的私有格式，自动存成规则 |

表中除「雷柏 / JBL / 八位堂 / 索尼 / HID 标准电池集合」是设备主动上报、「XInput / Windows 电池类」走系统接口外，其余都是程序主动发一帧查询。

> **列表里少一行，也不给假数字。**
> 解析不出确切百分比就不列出该设备，不显示 `--`，也不猜一个值。

**暂不支持**

| 情况 | 原因 |
|---|---|
| 蓝牙设备 | 只处理 2.4G 与 USB 有线 |
| 无电量接口的公版接收器（如 `258A:1007`） | 固件里没有电量字段 |
| 任天堂手柄 | USB / 蓝牙，不走 2.4G 接收器 |
| Lofree、IPI、EPOS 等 | 私有帧还没有样本，见[适配流程](#适配新设备) |
| 其余未覆盖品牌 | 按方案商适配，覆盖面随 Issues 里的报告增长 |

---

## 安装

**安装包**：到 [Releases](https://github.com/LargeAkon/WirelessBattery/releases/latest) 下载 `WirelessBatterySetup.exe`，双击安装。
约 43 MB，内置 Qt 运行时，不需要装 Python。可选安装路径、创建快捷方式、开机自启，自带卸载程序。

**从源码运行**：

```bash
git clone https://github.com/LargeAkon/WirelessBattery.git
cd WirelessBattery
python -m pip install -r requirements.txt
cd app && python main.py
```

需要 Python 3.10+ 与 Windows 10 / 11。只想挂在托盘、不弹卡片，用 `python main.py --tray`。

---

## 使用

<kbd>左键</kbd> 点托盘图标 → 设备卡片；<kbd>右键</kbd> → 菜单。

| 菜单项 | 作用 |
|---|---|
| 立即刷新 | 跳过冷却，强制重读所有通道 |
| 打开设置 | 刷新间隔、主题、毛玻璃、自启动 |
| 开机自启动 | 勾选即写注册表 |
| 设备诊断 | 端点列表 + 复制识别 + 导出报告 |
| 退出 | 完全退出 |

卡片上点设备可以改类型和显示名，识别错名字时用。

---

## 适配新设备

这是最需要的贡献方式。手上有读不到电量的设备时：

1. <kbd>右键</kbd>托盘 → **设备诊断**
2. 中间表格列出全部 HID 端点，每行右侧有「复制」
3. 找到标 **★** 的那行（厂商协议通道，页面 `0xFF00`），点「复制」
4. 内容自动填进下方输入框，点 **识别**
5. 仍失败就点 **导出诊断报告**，把生成的 txt 发到 [Issues](https://github.com/LargeAkon/WirelessBattery/issues)

报告里每个端点都标注了所属方案商（例如 `0C45 → Sonix 松翰公版`），据此能判断该补哪家协议，而不是按型号瞎猜。

---

## 开发

```bash
python -m pip install -r requirements.txt
python build.py            # → dist/WirelessBatterySetup.exe
```

流程：PyInstaller 打出程序本体 → 压成 `payload.tar.xz` → 内嵌进单文件安装向导。

```
app/
  main.py       托盘、菜单、刷新调度、充电动画
  scanner.py    通道调度 + 合并去重 + 失败缓存
  recognize.py  「复制端点 → 粘贴识别」的解析与探测
  brands.py     品牌 VID → 走哪套电量帧
  vendors.py    芯片与系统设备的方案商对照
  providers/    各条电量通道，一个文件一套协议
  ui/           卡片、诊断窗口、毛玻璃、图标绘制
installer/      安装向导（打包成单文件 Setup.exe）
tools/          开发期探针与冒烟脚本（不参与打包）
```

三条原则：

- **只读**：所有查询只问电量，不写配置、不改灯效、不碰固件。
- **多通道并行**：九条通道共用一次 HID 枚举，按 `VID:PID + 设备类型` 合并去重。
- **读不准就不读**：帧长度、校验、状态字段任一对不上就跳过。

---

## 隐私

不联网，没有任何 HTTP 请求，没有更新检查和统计上报。配置只存本机 `%APPDATA%\WirelessBattery\config.json`。
诊断报告只在你点击导出时生成到桌面，内容是本机 HID 端点列表，不会自动发送。

---

## License

[MIT](LICENSE) © 2026 Akon
