# -*- coding: utf-8 -*-
"""安装流程验证：以源码方式跑一遍解压/快捷方式/注册表写入，再清理。"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "installer"))

import setup as installer  # noqa: E402

TARGET = Path.home() / "WirelessBatteryInstallTest"


def main() -> int:
    payload = ROOT / "installer" / "payload.zip"
    if not payload.exists():
        print("缺少 payload.zip")
        return 1

    worker = installer.InstallWorker(TARGET, payload, True, True, True)
    worker.progress.connect(lambda pct, text: None)
    errors: list[str] = []
    worker.failed.connect(errors.append)
    worker.run()  # 同步执行

    if errors:
        print("安装失败:", errors)
        return 1

    exe = TARGET / installer.EXE_NAME
    print("主程序存在:", exe.exists(), exe.stat().st_size // 1024 // 1024, "MB")
    print("桌面快捷方式:", (Path.home() / "Desktop" / f"{installer.DISPLAY_NAME}.lnk").exists())
    print("开始菜单:", (Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" /
                       "Start Menu" / "Programs" / f"{installer.DISPLAY_NAME}.lnk").exists())
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, installer.RUN_KEY) as k:
        print("开机自启项:", winreg.QueryValueEx(k, installer.APP_NAME)[0])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, installer.UNINSTALL_KEY) as k:
        print("卸载注册表:", winreg.QueryValueEx(k, "DisplayName")[0],
              "|", winreg.QueryValueEx(k, "UninstallString")[0][:60], "...")

    # 清理：撤掉注册表与快捷方式，目录改名归档
    installer.set_run_key(False, exe)
    installer.remove_uninstall_entry()
    for link in (Path.home() / "Desktop" / f"{installer.DISPLAY_NAME}.lnk",
                 Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" /
                 "Start Menu" / "Programs" / f"{installer.DISPLAY_NAME}.lnk"):
        try:
            link.unlink()
        except Exception:
            pass
    if TARGET.exists():
        TARGET.rename(TARGET.with_name("WirelessBatteryInstallTest_done"))
    print("清理完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
