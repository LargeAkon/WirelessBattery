# -*- coding: utf-8 -*-
"""配置持久化 + 开机自启（HKCU，无需管理员）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "WirelessBattery"
# 与 installer/setup.py 的 VERSION 保持一致（诊断报告里会写出来，方便对版本）
APP_VERSION = "1.5.28"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# 刷新间隔只提供三档
INTERVALS = (10, 15, 20)

DEFAULTS = {
    "interval_minutes": 10,     # 刷新间隔：10 / 15 / 20 分钟
    "autostart": False,         # 开机自启（唯一权威来源，启动时同步到注册表）
    "theme": "dark",            # dark / light
    "glass": True,              # 卡片毛玻璃（关掉就是实底卡片）
    "overrides": {},            # 设备 key -> {"kind":..., "name":...}
    "custom_rules": [],         # 自定义报文规则（私有协议设备）
    "card_pinned": False,
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


class Config:
    def __init__(self) -> None:
        self.data = dict(DEFAULTS)
        self.load()

    # ---------- 读写 ----------
    def load(self) -> None:
        try:
            raw = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        self.data[k] = v
        except Exception:
            pass

    def save(self) -> None:
        try:
            config_path().write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()

    # ---------- 便捷属性 ----------
    @property
    def interval_minutes(self) -> int:
        try:
            v = int(self.data.get("interval_minutes", INTERVALS[0]))
        except Exception:
            v = INTERVALS[0]
        # 旧版本可能是 5 分钟，吸附到最近的可选档位
        return min(INTERVALS, key=lambda m: abs(m - v))

    @interval_minutes.setter
    def interval_minutes(self, v: int) -> None:
        self.set("interval_minutes", int(v))

    @property
    def interval_ms(self) -> int:
        return self.interval_minutes * 60 * 1000

    # ---------- 设备类型纠偏 ----------
    def override_for(self, key: str) -> dict:
        return (self.data.get("overrides") or {}).get(key) or {}

    def set_override(self, key: str, kind: str | None, name: str | None = None) -> None:
        ov = dict(self.data.get("overrides") or {})
        entry = dict(ov.get(key) or {})
        if kind:
            entry["kind"] = kind
        if name:
            entry["name"] = name
        ov[key] = entry
        self.set("overrides", ov)


# ---------------- 开机自启 ----------------
def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    main_py = Path(__file__).resolve().parent / "main.py"
    return f'"{exe}" "{main_py}" --tray'


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enable: bool) -> bool:
    """返回实际生效状态。"""
    import winreg

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return autostart_enabled() == bool(enable)
    except OSError:
        return False


def apply_autostart_preference(preference: bool) -> bool:
    """配置是唯一权威来源：启动时把注册表拉到与配置一致。

    安装时若未勾选自启，安装包会写入 autostart=false，
    即便系统里残留旧的启动项，这里也会把它清掉。
    """
    preference = bool(preference)
    if autostart_enabled() != preference:
        set_autostart(preference)
    return autostart_enabled()
