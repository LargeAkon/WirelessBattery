<div align="center">

<h1>WirelessBattery</h1>

<p>A Windows tray utility that shows the battery level of <b>2.4G wireless keyboards, mice, gamepads, and headsets</b> on one screen.</p>

<p>
<a href="README.zh-CN.md"><img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-0A0B0C?style=for-the-badge" alt="中文"></a>
</p>

<p>
<img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=flat-square&logo=windows11&logoColor=white" alt="Windows">
<img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square" alt="License">
<img src="https://img.shields.io/github/v/release/LargeAkon/WirelessBattery?style=flat-square&label=release&color=0A0B0C" alt="release">
<img src="https://img.shields.io/github/downloads/LargeAkon/WirelessBattery/total?style=flat-square&label=downloads" alt="downloads">
</p>

<p>
<a href="https://github.com/LargeAkon/WirelessBattery/releases/latest"><img src="https://img.shields.io/badge/Download-WirelessBatterySetup.exe-2ea44f?style=for-the-badge&logo=windows&logoColor=white" alt="Download"></a>
</p>

<p>
<a href="#interface">Interface</a> ·
<a href="#supported-devices">Supported devices</a> ·
<a href="#install">Install</a> ·
<a href="#usage">Usage</a> ·
<a href="#adding-a-device">Adding a device</a> ·
<a href="#development">Development</a>
</p>

</div>

---

## Interface

<div align="center">
  <img src="docs/tray.png" width="760" alt="Tray icon at each battery level">
  <br><sub>Tray icon: the filled length of the battery body is the charge left. While charging, green fills from left to right.</sub>
</div>

<div align="center">
  <img src="docs/card-light.png" width="380" alt="Device card, light theme">
  <img src="docs/card.png" width="380" alt="Device card, dark theme">
  <br><sub>Device card: left-click the tray icon. Every online device is on one screen.</sub>
</div>

---

## Features

| | |
|---|---|
| **Tray reading** | The fill inside the battery icon follows the level. While plugged in it fills frame by frame, so you can see it without opening the card. |
| **Hover to show** | Resting the pointer on the tray icon opens the card. Only a clicked card stays pinned and stops following the pointer. |
| **Several devices** | Keyboards, mice, gamepads, and headsets are listed together, each with its own bar and connection type. |
| **Sleep keeps the last reading** | When a device drops, the last reading stays and is marked signal lost. It does not blink out. |
| **Refresh** | Normally every 10, 15, or 20 minutes. Once a device is charging, refresh tightens to 30 seconds. |
| **Theme animation** | Light, dark, and acrylic switches uncover in a circle: the new skin spreads from the option you clicked. |
| **One-click diagnosis** | One click runs every protocol channel, lists endpoints, and writes why a device could not be read. |
| **Add a device** | On the diagnosis page: pick the receiver, pick a searchable brand and model, try a read, then add it as an external profile. |
| **Profile library** | 57 vendor profiles in 28 brand groups. A model that passes a trial read is polled on later refreshes. |
| **Start with Windows** | Writes the HKCU Run key. No administrator rights. The uninstaller removes it. |

---

## Supported devices

2.4G has no shared battery standard. Bluetooth has the GATT Battery Service; each 2.4G vendor has its own private report. This app does not read a generic interface. It implements the protocol of each wireless-chip vendor. There are hundreds of brands and about a dozen chip vendors.

| Vendor / channel | Coverage |
|---|---|
| **HID++ 2.0** | Logitech: G Pro, GPW, MX Master, G913, and the rest of the family |
| **Evision** | ATK, VGN, VXE, and WOBKEY keyboards and mice (`VID 320F`, `FF1C:0092`). WOB keyboards (Rainy75 / Wave75) answer slowly, up to 14 seconds |
| **Compx 17-byte frame** | Receivers on page `FF02`, regardless of brand: ATK, VXE, VGN mice, Dareu, Pulsar, Attack Shark, AULA keyboards, Ninjutso, Incott, Hitscan, Scyrox, Finalmouse, Ajazz, and other rebrands |
| **Nordic 54** | ATK Zero and similar (`VID 373B`, page `FF05`) |
| **Feature report 0x83** | WLmouse, Langzu, G-Wolves, MCHOSE; and Sinowealth reference designs used by AULA, EWEADN, and some Ajazz and Delux devices |
| **MCHOSE G7** | `AA 30` reply on `VID A8A5` |
| **Razer** | Query frames `0x07` / `0x80` |
| **ASUS** | ROG / TUF (`12 07` / `12 01`) |
| **VAXEE** | VAXEE wireless mice |
| **Angry Miao / Ajazz / Akko** | The same status report `0x05` (`VID 3151`) |
| **SteelSeries** | `b0` on Arctis Nova 7 Gen2, `d2` on Aerox, `aa` on Rival 3 |
| **Flydigi** | GET_INFO on Vader 5 Pro (`VID 37D7`). Older models only expose the system four-step scale, which is not converted into a percentage |
| **HyperX** | HyperX 2.4G headsets, matched by product id. Cloud III Wireless `03F0:05B7` / `0C9D` / `0FCC`, commands on the control pipe. Cloud III S `02CC` |
| **Rapoo / JBL** | The receiver reports on its own. The app only listens |
| **8BitDo / Sony** | Input reports from DualShock 4 and 8BitDo gamepads. DualSense is Bluetooth or wired only, and is not read |
| **Packs (per-model private protocols)** | The table below. A hit needs both the interface fingerprint and a valid frame |
| **Added profiles** | Models that passed a manual trial read under Add device, stored as external profiles and polled on refresh |

Except Rapoo, JBL, 8BitDo, and Sony, which push their own reports, every other row sends one query frame.

> **A missing row is better than a made-up number.**
> If the reply does not parse to an exact percentage, the device is left off the list. There is no `--`, and no guessed value.

**Profile library**

| Brand | Models |
|---|---|
| VXE | V3 NK / R1 Nearlink, R1 Pro Max / R1 SE |
| ATK | F1 Pro Max / F1 V3 / F1 Ultimate, F1 Moba F503, A9 Air Master+, Z87 keyboards, A87 Pro, V75X, N9V2 Ultimate headset, Nordic 54 mice |
| VGN | Beiying keyboard, Dragonfly3 SE, F1 Pro (4K), F2 Master+, F1 V5 Turbo+, V98 Pro, ryMs receivers (3 Pro Max / Y2 V2 Pro Max / F1 V2 Pro Max / 3 Ultra / F1 V5 Ultra / F2 V2 Ultra) |
| MCHOSE | G75 Pro / Z75S / K99 / GX87 / G75 keyboards, A7 V3 Pro / Ultra+, V9 Turbo+ headset, G7 |
| Lingbao | K98 keyboard, M1 Pro, M5PRO Max |
| AULA | F99 Pro, F108 Pro |
| LEOBOG | Hi75c Pro, HI98PRO |
| Titanium / IMECOO | TSG809, HJSDZHI S1-V2, P1 |
| ASUS ROG | AZOTH Omni keyboards, HARPE / KERIS Omni, Keris AimPoint, SPEEDNOVA 8K, PELTA / DELTA II headsets |
| HyperX | Cloud II Wireless, Cloud III / II Core, Cloud III S (`03F0:02CC`), Alpha 2, Alpha Wireless |
| Edifier HECATE | G3M Pro, G5M Pro |
| Other | Dareu A950 AIR V2, Siberia T7 / T7 GT, Pulsar X2 / Link 8K, Scyrox 8K, Hitscan Hyperlight, CROCIRIS X7, CHERRY MX 2.0S WL Pro, MOONDROP GM01 Pro, GANSS GS3104T-Pro, SHADOW, EWEADN S9 PRO, Delux GH8K / M900 Ultra, BETOP KP40D, VAXEE / ZYGEN |

**Protocol packs**

Frame layouts come from captures of the official software or from public reverse-engineering notes, and each one checks the reply. A pack that can listen never sends a frame. Only 2.4G receivers and USB wired links are handled. Bluetooth is not.

| Brand | Model | VID:PID | Frame | Status |
|---|---|---|---|---|
| PULSAR | X2 V2 | `3554:F508` | 17-byte STATUS/POWER, checksum `0x55 - sum` | Verified locally by the upstream project |
| CHERRY | PIXIU75 | `046A:01E4` / `01E2` | 64-byte block protocol, block `0x1A` is the level | Upstream hardware |
| ASUS ROG | Strix Scope II 96 (Omni receiver) | `0B05:1ACE` | `A0` checks the pairing table, then `12 01` reads the level | Upstream hardware, 95% |
| ASUS ROG | Wireless headset | `0B05:1AFA` | `0xCC` frame: `12 07` level, `12 08` charging | Upstream hardware |
| INPHIC | ZHEN | `1D57:FA65` | Passive `0x03` frame (`76 41`) | Upstream hardware |
| DELUX | M900 Pro | `1D57:FA65` | Passive `0x03` frame (`30 40`) | Upstream hardware |
| HECATE | G5M Pro | `35BB:D00B` | `0x04` frame (`1A` marker) plus one query | Upstream hardware |
| GameSir | G7 Pro CE | `3537:*` | `0x12` status stream plus `0F F2 00` heartbeat | Upstream hardware |
| AJAZZ | AK870 | `3151:4011` | Feature `F7 08` mailbox query | Upstream hardware |
| LINGBAO | M5PRO Max | `3151:402D` | Feature `F7` status query | Upstream hardware |
| LINGBAO | K98 | `3554:FA09` | `0x13` session / push, model password `0x0212` selects the path | Contributor hardware |
| THUNDEROBOT | ML903 NearLink Se | `369B:0234` | `A0 02` TLV (tag `0x0225` is the level) | Upstream hardware |
| EWEADN | X87 keyboard | `0C45:FEFE` | 33-byte frame, checksum at `[32]` | Upstream hardware |
| EWEADN | S9 mouse | `372E:1026` | BASICS mailbox of feature `0x03` | Upstream hardware |
| RAPOO | VT3 gen 2 | `24AE:*` | Passive report `0x07` status frame | Verified locally by the upstream project |
| MOJHON | GALE2 | `E2B7:122C` | `A4` register `0x04` read/write, checksum in the last byte | Upstream hardware |
| AKG | N9 Hybrid | `0ECB:20D9` | Receiver RACE battery query | Contributor hardware, 50% |
| SHADOW | SHADOW | `3654:6901` | `FE` magic GetBasicInfo, `0x80` is the charging bit | Upstream hardware |
| GANSS / AULA | GS3104T-Pro / F108 Pro | `05AC:024F` | 33-byte query (same fingerprint, one shared switch) | Contributor hardware |
| BETOP | T9 / Kunpeng 20 | `20BC` / `20DD` | Passive 2.4G broadcast plus a wired query | T9 local, Kunpeng 20 from a contributor |
| AULA | F99 Pro | `3554:FA09` | `0x13` session plus `0x0A` push / `0x4A` reply | Contributor hardware |
| AULA | G9 headset | `38A6:0030` | Passive `0xAB` status frame | Contributor report |
| AULA | L9 Ultra mouse | `38A6:28FD` | `0x81` query, level / charging at `[17]` / `[18]` | Contributor report |
| AULA | HERO 68 Air | `372E:106C` | 8K receiver Bytech fragmented query | Contributor hardware |
| VGN | Dragonfly F1 V5 Turbo+ / F2 Master+ | `391D:1A23` / `1026` | kc2 config frame (`0xB3/0x06`), `0x80` is the charging bit | Contributor hardware |
| VGN | Y2 | `3554:FB56` / `FB57` | `0x08/0x04` query | Contributor hardware |
| VGN | V98 Pro | `320F:*` | `0x1A` query; after a cable is plugged in, the serial keeps a single interface | Contributor hardware |
| ATK / VXE | Wireless mice / A98 Pro | `373B:*` | 17-byte query (mouse) / VIA (keyboard) | Two mice on real hardware |
| RAZER | Viper V4 Pro | `1532:00E6` / `00E5` | Classic 90-byte feature (`0x07/0x80`, `0x84` charging) | Verified locally by the upstream project |
| RAZER | Viper V3 Pro SE | `1532:00DF` | Dedicated battery-query frame | Verified locally by the upstream project |
| RAZER | BlackShark V2 Pro (2023) | `1532:0555` | PA remote mode: `0x21` level, `0x2A` charging | Upstream local check, 79% |
| RAZER | Kraken V4 | `1532:056C` | 64-byte `0x02` query | Contributor report |
| MCHOSE | G87 / G87 V2 / K99 / X75 family | `3837` / `41E4` | `0x13` session ACK plus `0x0A` push, bit 4 is charging | Local G87 V1 |
| MCHOSE | G87 V2 / A7 V2 Pro | `3837` / `41E4` | Mouse V2 passive `0xE2` inverted-checksum frame | Contributor hardware |
| MCHOSE | K7 V2 Ultra+ | `3837:1018` | `0x0900` query plus `0x0600` events | Contributor hardware |
| MCHOSE | G3 V2 | `3837:4245` | Gmouse active query (`55 30 A5…`) | Contributor hardware |
| MCHOSE | A5 V2 Ultra | `3837:100C` | Inverted-checksum feature `0x11` | Contributor report |
| MCHOSE | V9 Pro / X9 headsets | `291D:385D` / `3837:6045` | 64-byte `55 65 01` query | V9 on hardware, X9 reported |
| MCHOSE | G75 Pro | `3554:FA09` | Same fingerprint as AULA F99 Pro; the session ACK selects the model | Contributor hardware |
| MCHOSE | Newer QHW dongle | for example `3837:3033` | `0x4D` handshake, then `0x0904` query / CZ push | Waiting for a matching device |
| SONY | INZONE H9 II | `054C:0FA8` | `0xFF04` control transfer (must use SET_REPORT) | Verified locally by the upstream project |
| Haute42 | Adapter 4DS | `054C:0CE6` | Read-only feature `0xF9`, identified by the firmware string | Contributor report |
| HyperX | Cloud Flight 2 | `03F0:0AC1` | Passive `0xFB` event (`0x13` is the level) | Upstream hardware |

"Upstream" in the table is a result from vigil-watt hardware. Every decoder here is checked against that project's captured frames (`tools/test_packs.py`, 178 cases). The interface has a separate offline suite (`tools/test_reveal.py`): if a theme animation dies halfway, or Windows drops the tray rectangle back to the middle of the screen, no cover may be left behind and the card may not be thrown to the center. The theme cover must be a child of the card, never its own window, and the frame at 43% must actually be the old skin with the new skin inside the circle. It must not jump to the end, and it must not sit still. Families that write a frame (Razer, MCHOSE, K7, A5, AKG, GANSS, ATK/VGN, BETOP, ASUS, CHERRY, Thunderobot, Lingbao, MOJHON, EWEADN, HECATE, Sony, Haute42) send one query per round by default, then cool down for 150 seconds after a failure.

Pack code is split by **mouse / keyboard / headset / gamepad**, one file per brand. A brand that spans types has the same file name in more than one directory (`mouse/vgn.py` is the Dragonfly mice, `keyboard/vgn.py` is the V98 Pro). To add a device, see [`app/providers/packs/README.md`](app/providers/packs/README.md): the three-step flow, a template, and the match rules.

**Not supported yet**

| Case | Why |
|---|---|
| Bluetooth devices | Only 2.4G and USB wired |
| Reference receivers with no battery field (for example `258A:1007`) | The firmware has no level field |
| Nintendo controllers | USB / Bluetooth, not a 2.4G receiver |
| Xbox controllers | Windows only reports four steps (5 / 25 / 60 / 100). Those steps are not turned into a percentage |
| Lofree, IPI, EPOS, and similar | No captured private frame yet. Try Add device, then Auto-detect, on the diagnosis page |
| Other brands | Added per chip vendor, as reports come in through Issues |

---

## Install

**Installer.** Download `WirelessBatterySetup.exe` from [Releases](https://github.com/LargeAkon/WirelessBattery/releases/latest) and double-click it. About 43 MB, with the Qt runtime included, so Python is not required. You can choose the folder, create shortcuts, and turn on start with Windows. An uninstaller is included.

**From source:**

```bash
git clone https://github.com/LargeAkon/WirelessBattery.git
cd WirelessBattery
python -m pip install -r requirements.txt
cd app && python main.py
```

Python 3.10+ and Windows 10 / 11. Use `python main.py --tray` to sit in the tray without opening the card.

---

## Usage

Rest the pointer on the tray icon and the card opens. <kbd>Left click</kbd> pins or closes it. <kbd>Right click</kbd> opens the menu.

| Menu | What it does |
|---|---|
| Refresh now (立即刷新) | Skip the cooldown and read every channel again |
| Open settings (打开设置) | Interval, theme, acrylic, start with Windows |
| Start with Windows (开机自启动) | Checking it writes the registry key |
| Device diagnosis (设备诊断) | Find devices, add one by hand, export a report |
| Quit (退出) | Exit completely |

Click a device on the card to change its type or display name when the detected name is wrong.

---

## Adding a device

This is the most useful contribution. If a device's level cannot be read:

1. <kbd>Right-click</kbd> the tray icon, then **Device diagnosis** (设备诊断), then **Find devices** (自动查找设备).
2. If it is still missing, use **Add device** (添加设备) at the top right: select that receiver, pick your model, and click **Try read** (试读).
3. If you do not know the model, click **Auto-detect** (自动探测). Templates in the library are tried one by one. Two identical readings count as a hit.
4. If that still fails, click **Export report** (导出报告) and attach the desktop `.txt` to [Issues](https://github.com/LargeAkon/WirelessBattery/issues).

Each endpoint in the report is labeled with its chip vendor (for example `0C45 → Sonix`), and the raw receiver frames are included. That shows which protocol to add, instead of guessing from the model name.

---

## Development

```bash
python -m pip install -r requirements.txt
python build.py            # → dist/WirelessBatterySetup.exe
```

PyInstaller builds the app, the build packs it into `payload.tar.xz`, and that archive is embedded in the single-file setup wizard.

```
app/
  main.py       tray, menu, refresh schedule, charge animation
  trayhover.py  hover on the tray icon opens the card
  scanner.py    channel schedule, merge, failure cache
  profiles.py   profile engine: send the frame, read the offset, check the reply
  profiles_data.py  57 built-in vendor profiles (data only)
  autodiag.py   one-click diagnosis: every channel, the endpoint list, and why a device was missed
  brands.py     brand VID → which battery frame
  vendors.py    chip and system-device vendor names
  providers/    one file per battery channel
    registry.py   channel list and source rules
    packs/        per-model private protocols, grouped by device type, brand, then model
      mouse/        mice: vgn.py is Dragonfly F1/F2, razer.py is Viper
      keyboard/     keyboards: vgn.py is V98 Pro, cherry.py is PIXIU75
      headset/      headsets: sony.py is INZONE H9 II, akg.py is N9 Hybrid
      gamepad/      gamepads: gamesir.py is G7 Pro, betop.py is BETOP
      README.md     which file to edit for a new device
    added.py      external profiles written by Add device
  ui/           card, diagnosis window, theme animation, acrylic, icons
installer/      setup wizard, packed as one Setup.exe
tools/          probes and smoke scripts, not packed into the installer
```

Four rules:

- **Read only.** Queries ask for the battery level. They do not write settings, change lighting, or touch firmware.
- **Do not interrupt typing.** On a 2.4G keyboard the vendor command and the key reports share one radio link, and on the receiver they are often two collections of the same HID interface. Inserting a frame while typing pushes key-up until the command round-trip finishes. Each write waits until the system has been idle for 0.6 seconds. If that wait fails, the round is skipped and tried again next time. A round sends at most two frames, and once a layout is confirmed only that layout is sent.
- **Channels share one enumeration.** The channel list and priorities live in `providers/registry.py`. Results are merged by `VID:PID` plus device type.
- **No match, no number.** A wrong length, checksum, or status field is a miss. A percentage is never invented from a nearby byte.

---

## Privacy

The app does not connect to the network. There is no HTTP request, no update check, and no telemetry. Settings stay in `%APPDATA%\WirelessBattery\config.json` on this PC. A diagnosis report is written to the desktop only when you export it. It is a list of local HID endpoints, and it is not sent anywhere.

---

## License

[MIT](LICENSE) © 2026 Akon
