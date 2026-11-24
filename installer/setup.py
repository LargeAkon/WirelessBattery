# -*- coding: utf-8 -*-
"""外设电量 —— 安装向导。

打包后为单文件 Setup.exe，内置程序本体压缩包；
支持自选安装路径、创建快捷方式、开机自启、以及卸载。
"""
from __future__ import annotations

import ctypes
import io
import json
import lzma
import os
import shutil
import subprocess
import sys
import tarfile
import winreg
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

APP_NAME = "WirelessBattery"
DISPLAY_NAME = "外设电量"
VERSION = "1.5.40"
PUBLISHER = "Local"
EXE_NAME = "WirelessBattery.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\WirelessBattery"

# 浅色体系：白纸面 + 黑墨，与软件浅色主题同一套色
BG = "#FFFFFF"
SOFT = "#FAFAFB"
PANEL = "#FCFCFD"
CARD = "#F4F4F6"
TEXT = "#0A0B0C"
SUB = "#5F646C"
DIM = "#9AA0A8"
LINE = "#EBEBEF"
LINE_STRONG = "#D6D8DE"


def resource(name: str) -> Path:
    """资源定位：打包后资源在 _MEIPASS 根目录，源码运行时在 assets/。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidates = (
        base / name,
        base / "assets" / name,
        Path(__file__).resolve().parent.parent / "assets" / name,
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def qss_url(name: str) -> str:
    path = resource(name)
    return str(path).replace("\\", "/")


def default_dir() -> Path:
    # 升级安装：沿用上次的安装位置，避免出现两份程序
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            location, _ = winreg.QueryValueEx(k, "InstallLocation")
            if location and Path(location).exists():
                return Path(location)
    except OSError:
        pass
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP_NAME


# ---------------- 快捷方式 / 注册表 ----------------
def make_shortcut(link: Path, target: Path, workdir: Path) -> bool:
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{target}';$s.WorkingDirectory='{work}';"
        "$s.IconLocation='{target},0';$s.Save()"
    ).format(link=link, target=target, work=workdir)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=25, creationflags=0x08000000,
        )
        return link.exists()
    except Exception:
        return False


def set_run_key(enable: bool, exe: Path) -> None:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{exe}" --tray')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def run_key_present() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def write_app_config(autostart: bool) -> None:
    """把安装时的选择写进程序配置，程序启动时以此为准。

    之前的问题是：注册表里若有历史自启项，程序启动会读注册表并把
    界面点亮，看起来"去掉了勾选却还是开着"。现在安装包显式落一份
    配置，程序启动时反向校正注册表，状态就一定跟着勾选走。
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / APP_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "config.json"
        data: dict = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
        data["autostart"] = bool(autostart)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:
        pass


def write_uninstall_entry(install_dir: Path, size_kb: int) -> None:
    uninstaller = install_dir / "uninstall.exe"
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, DISPLAY_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ,
                              str(install_dir / EXE_NAME))
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                              f'"{uninstaller}" --uninstall')
            winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ,
                              f'"{uninstaller}" --uninstall --silent')
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except OSError:
        pass


def remove_uninstall_entry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def light_title_bar(widget: QWidget) -> None:
    """强制浅色标题栏，避免系统深色模式下窗口边框变黑、和白色主体割裂。"""
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def apply_light_theme(app: QApplication) -> None:
    """固定浅色外观。

    系统若开着深色模式，Qt 会跟着变暗，消息框就会变成黑底白字，和白色
    安装窗口拼在一起非常割裂。这里显式给一套浅色调色板兜住。
    """
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BG))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(TEXT))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(BG))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(DIM))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(DIM))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DIM))
    app.setPalette(pal)


# ---------------- 安装线程 ----------------
class InstallWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, target: Path, payload: Path, desktop_link: bool,
                 start_menu_link: bool, autostart: bool):
        super().__init__()
        self.target = target
        self.payload = payload
        self.desktop_link = desktop_link
        self.start_menu_link = start_menu_link
        self.autostart = autostart

    def run(self) -> None:
        try:
            self.target.mkdir(parents=True, exist_ok=True)
            # tar.xz 是整体压缩（solid），一次性解开再按成员落盘，比逐文件
            # zip 解压快，也让安装包小了一大截
            self.progress.emit(6, "解压安装文件")
            raw = lzma.decompress(self.payload.read_bytes())
            self.progress.emit(30, "写出程序文件")
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
                members = [m for m in tf.getmembers() if m.isfile()]
                total = len(members) or 1
                for index, member in enumerate(members, 1):
                    tf.extract(member, self.target, filter="data")
                    if index % 12 == 0 or index == total:
                        pct = 30 + int(index / total * 46)
                        self.progress.emit(pct, f"解压文件 {index}/{total}")
            raw = b""

            exe = self.target / EXE_NAME
            if not exe.exists():
                self.failed.emit("解压后未找到主程序，压缩包可能已损坏。")
                return

            self.progress.emit(82, "创建快捷方式")
            # 清掉上一代程序名的旧快捷方式，避免桌面上两个图标
            for old in (
                Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "无线外设电量.lnk",
                Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
                "Start Menu" / "Programs" / "无线外设电量.lnk",
            ):
                try:
                    old.unlink()
                except Exception:
                    pass
            if self.desktop_link:
                make_shortcut(Path(os.environ["USERPROFILE"]) / "Desktop" /
                              f"{DISPLAY_NAME}.lnk", exe, self.target)
            if self.start_menu_link:
                start_menu = (Path(os.environ.get("APPDATA", ""))
                              / "Microsoft" / "Windows" / "Start Menu" / "Programs")
                make_shortcut(start_menu / f"{DISPLAY_NAME}.lnk", exe, self.target)

            self.progress.emit(90, "写入启动项与配置")
            # 先清掉历史启动项，避免旧安装残留与本次勾选不一致
            set_run_key(False, exe)
            if self.autostart:
                set_run_key(True, exe)
            write_app_config(self.autostart)

            try:
                size_kb = sum(f.stat().st_size for f in self.target.rglob("*")
                              if f.is_file()) // 1024
            except Exception:
                size_kb = 0
            write_uninstall_entry(self.target, size_kb)

            try:
                if getattr(sys, "frozen", False):
                    shutil.copy2(sys.executable, self.target / "uninstall.exe")
            except Exception:
                pass

            self.progress.emit(100, "安装完成")
            self.finished_ok.emit(str(exe))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ---------------- 安装界面 ----------------
class OptionRow(QWidget):
    """一行可点击的勾选项：左边勾选框，右边标题 + 一行说明。

    整行都能点，不必精确点到那个 17px 的小方块；说明文字压在标题下面一行，
    比"标题（括号里塞解释）"清楚得多。
    """

    def __init__(self, title: str, desc: str, checked: bool = True):
        super().__init__()
        self.setObjectName("OptRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(58)

        row = QHBoxLayout(self)
        # 上留 13px：让勾选框与第一行标题对齐，而不是落在两行文字中间
        row.setContentsMargins(15, 13, 15, 0)
        row.setSpacing(11)

        self.check = QCheckBox()
        self.check.setObjectName("OptCheck")
        self.check.setChecked(checked)
        self.check.setFixedSize(17, 17)
        self.check.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.check, 0, Qt.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("OptTitle")
        desc_label = QLabel(desc)
        desc_label.setObjectName("OptDesc")
        texts.addWidget(title_label)
        texts.addWidget(desc_label)
        row.addLayout(texts, 1)

    def isChecked(self) -> bool:
        return self.check.isChecked()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.check.toggle()
        super().mouseReleaseEvent(event)


class SetupWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{DISPLAY_NAME} 安装向导")
        self.setFixedSize(620, 580)
        self.setWindowIcon(QIcon(str(resource("app.ico"))))
        self._worker: InstallWorker | None = None

        self.setStyleSheet(f"""
        QWidget {{ background:{BG}; color:{TEXT};
                   font-family:"Microsoft YaHei UI"; font-size:12px; }}
        QLabel, QCheckBox {{ background:transparent; border:none; }}
        QWidget#Header {{ background:{SOFT}; border-bottom:1px solid {LINE}; }}
        QWidget#Footer {{ background:{BG}; border-top:1px solid {LINE}; }}
        QLabel#H1 {{ font-size:20px; font-weight:700; }}
        QLabel#Sub {{ color:{SUB}; font-size:12px; }}
        QLabel#Sect {{ color:{DIM}; font-size:11px; font-weight:600; }}
        QLabel#Hint {{ color:{DIM}; font-size:11px; }}
        QLabel#Status {{ color:{SUB}; font-size:11px; }}
        QLabel#OptTitle {{ color:{TEXT}; font-size:12px; }}
        QLabel#OptDesc {{ color:#8A9099; font-size:11px; }}
        QWidget#OptRow {{ background:transparent; }}
        QWidget#OptRow:hover {{ background:rgba(0,0,0,0.028); }}
        QFrame#Panel {{ background:{PANEL}; border:1px solid {LINE};
                        border-radius:12px; }}
        QFrame#Sep {{ background:{LINE}; border:none; }}
        QLineEdit {{ background:{BG}; border:1px solid {LINE_STRONG};
                     border-radius:9px; padding:0 12px; color:{TEXT};
                     font-size:12px; selection-background-color:{TEXT};
                     selection-color:{BG}; }}
        QLineEdit:focus {{ border:1px solid #A9AEB6; }}
        QPushButton#Primary {{ background:{TEXT}; border:none; border-radius:9px;
                               color:#FFFFFF; font-size:13px; font-weight:600; }}
        QPushButton#Primary:hover {{ background:#24262A; }}
        QPushButton#Primary:pressed {{ background:#000000; }}
        QPushButton#Primary:disabled {{ background:#C7C9CE; color:#FFFFFF; }}
        QPushButton#Ghost {{ background:{BG}; border:1px solid {LINE_STRONG};
                             border-radius:9px; color:{SUB}; font-size:12px; }}
        QPushButton#Ghost:hover {{ background:{CARD}; color:{TEXT}; }}
        QPushButton#Ghost:disabled {{ color:#C4C7CC; border-color:{LINE}; }}
        QCheckBox#OptCheck::indicator {{ width:17px; height:17px;
                                         image:url("{qss_url('box.png')}"); }}
        QCheckBox#OptCheck::indicator:checked {{
            image:url("{qss_url('check.png')}"); }}
        QProgressBar {{ background:{LINE}; border:none; border-radius:3px; }}
        QProgressBar::chunk {{ background:{TEXT}; border-radius:3px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部：图标 + 名称 + 一行说明 ----
        header = QWidget()
        header.setObjectName("Header")
        header.setAttribute(Qt.WA_StyledBackground, True)
        head = QHBoxLayout(header)
        head.setContentsMargins(26, 22, 26, 20)
        head.setSpacing(14)

        icon_label = QLabel()
        pix = QPixmap(str(resource("app.ico")))
        if not pix.isNull():
            icon_label.setPixmap(pix.scaled(48, 48, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        head.addWidget(icon_label, 0, Qt.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        h1 = QLabel(DISPLAY_NAME)
        h1.setObjectName("H1")
        sub = QLabel(f"版本 {VERSION}　·　无线键鼠耳机电量，常驻任务栏右下角")
        sub.setObjectName("Sub")
        titles.addWidget(h1)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        root.addWidget(header)

        # ---- 主体 ----
        body = QVBoxLayout()
        body.setContentsMargins(26, 20, 26, 16)
        body.setSpacing(0)

        body.addWidget(self._sect("安装位置"))
        body.addSpacing(9)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_edit = QLineEdit(str(default_dir()))
        self.path_edit.setFixedHeight(38)
        path_row.addWidget(self.path_edit, 1)
        self.browse_btn = QPushButton("浏览…")
        self.browse_btn.setObjectName("Ghost")
        self.browse_btn.setFixedSize(78, 38)
        self.browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.browse_btn)
        body.addLayout(path_row)

        body.addSpacing(8)
        body.addWidget(self._hint("默认安装到当前用户目录，不需要管理员权限"))

        body.addSpacing(22)
        body.addWidget(self._sect("安装选项"))
        body.addSpacing(10)

        self.panel = QFrame()
        self.panel.setObjectName("Panel")
        panel_lay = QVBoxLayout(self.panel)
        panel_lay.setContentsMargins(1, 1, 1, 1)
        panel_lay.setSpacing(0)
        self.row_autostart = OptionRow("开机自动启动", "登录 Windows 后自动在托盘常驻", True)
        self.row_desktop = OptionRow("创建桌面快捷方式", "在桌面放置一个启动图标", True)
        self.row_start = OptionRow("创建开始菜单快捷方式", "可在开始菜单里搜索到", True)
        self.row_launch = OptionRow("安装完成后立即运行", "装好立刻打开一次", True)
        for index, row in enumerate((self.row_autostart, self.row_desktop,
                                     self.row_start, self.row_launch)):
            if index:
                sep = QFrame()
                sep.setObjectName("Sep")
                sep.setFixedHeight(1)
                panel_lay.addWidget(sep)
            panel_lay.addWidget(row)
        body.addWidget(self.panel)

        body.addStretch(1)
        body.addSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        body.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("Status")
        self.status.setVisible(False)
        body.addWidget(self.status)
        root.addLayout(body, 1)

        # ---- 底部：只有按钮，不放任何说明文字 ----
        footer = QWidget()
        footer.setObjectName("Footer")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(26, 14, 26, 16)
        foot.setSpacing(10)
        foot.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.setFixedSize(88, 38)
        self.cancel_btn.clicked.connect(self.close)
        foot.addWidget(self.cancel_btn)
        self.install_btn = QPushButton("开始安装")
        self.install_btn.setObjectName("Primary")
        self.install_btn.setFixedSize(128, 38)
        self.install_btn.clicked.connect(self._install)
        foot.addWidget(self.install_btn)
        root.addWidget(footer)

    def _sect(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Sect")
        return label

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Hint")
        return label

    def showEvent(self, event) -> None:
        super().showEvent(event)
        light_title_bar(self)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择安装位置",
                                                  self.path_edit.text())
        if chosen:
            self.path_edit.setText(str(Path(chosen) / APP_NAME))

    def _install(self) -> None:
        target = Path(self.path_edit.text().strip())
        if not target.is_absolute() or len(str(target)) < 4:
            QMessageBox.warning(self, "路径无效", "请选择一个有效的安装位置。")
            return
        payload = resource("payload.tar.xz")
        if not payload.exists():
            QMessageBox.critical(self, "安装包损坏", "未找到内置的程序文件。")
            return

        self.install_btn.setEnabled(False)
        self.install_btn.setText("安装中…")
        self.cancel_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.path_edit.setReadOnly(True)
        self.panel.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setVisible(True)
        self.status.setText("准备安装…")

        self._worker = InstallWorker(
            target, payload,
            self.row_desktop.isChecked(), self.row_start.isChecked(),
            self.row_autostart.isChecked(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(
            lambda exe: self._done(exe, self.row_launch.isChecked()))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, pct: int, text: str) -> None:
        self.progress.setValue(pct)
        self.status.setText(text)

    def _on_failed(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.install_btn.setText("重新安装")
        self.cancel_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.path_edit.setReadOnly(False)
        self.panel.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("安装失败")
        QMessageBox.critical(self, "安装失败", message)

    def _done(self, exe: str, launch: bool) -> None:
        self.progress.setValue(100)
        self.status.setText("安装完成")
        if launch:
            try:
                subprocess.Popen([exe, "--tray"], cwd=str(Path(exe).parent),
                                 creationflags=0x00000008)
            except Exception:
                pass
        state = "已开启" if run_key_present() else "未开启"
        QMessageBox.information(
            self, "安装完成",
            f"{DISPLAY_NAME} 已安装到：\n{Path(exe).parent}\n\n"
            f"开机自启动：{state}\n\n"
            "程序将在任务栏右下角常驻，单击图标查看电量。",
        )
        self.close()


# ---------------- 卸载 ----------------
def uninstall(silent: bool = False) -> int:
    install_dir = Path(sys.executable).resolve().parent
    set_run_key(False, install_dir / EXE_NAME)
    write_app_config(False)
    remove_uninstall_entry()

    for link in (
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" / f"{DISPLAY_NAME}.lnk",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
        "Start Menu" / "Programs" / f"{DISPLAY_NAME}.lnk",
    ):
        try:
            link.unlink()
        except Exception:
            pass

    subprocess.run(["taskkill", "/f", "/im", EXE_NAME],
                   capture_output=True, creationflags=0x08000000)

    marker = install_dir / "_uninstall.cmd"
    try:
        marker.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'rmdir /s /q "{install_dir}"\r\n'
            "del /f /q \"%~f0\"\r\n",
            encoding="mbcs", errors="ignore",
        )
        subprocess.Popen(["cmd", "/c", str(marker)],
                         creationflags=0x08000000)
    except Exception:
        shutil.rmtree(install_dir, ignore_errors=True)

    if not silent:
        QMessageBox.information(None, "卸载完成",
                                f"{DISPLAY_NAME} 已卸载。")
    return 0


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(f"{DISPLAY_NAME} 安装向导")
    apply_light_theme(app)

    if "--uninstall" in sys.argv:
        silent = "--silent" in sys.argv
        if not silent:
            if QMessageBox.question(
                None, "卸载确认",
                f"确定要卸载 {DISPLAY_NAME} 吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return 0
        return uninstall(silent=silent)

    win = SetupWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
