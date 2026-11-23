# -*- mode: python ; coding: utf-8 -*-
"""主程序打包配置（onedir）。

不用命令行的 --exclude-module，是因为 PySide6 的 hook 会把整个包的 DLL、
翻译、Qml 全收进来，事后裁剪既慢又容易被文件锁/安全策略卡住。
这里在 Analysis 之后直接过滤 binaries / datas，从源头就不进包。
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).resolve()
APP = ROOT / "app"

# 按文件名剔除：程序用不到、或被 Qt 自己牵连进来的模块
DROP_NAMES = {
    # 无用 Qt 模块
    "opengl32sw.dll",
    "Qt6Quick.dll", "Qt6QuickControls2.dll", "Qt6QuickWidgets.dll",
    "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
    "Qt6QmlMeta.dll", "Qt6Pdf.dll", "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll", "Qt6VirtualKeyboard.dll", "Qt6Svg.dll",
    # Qt 的 TLS 后端与它拉来的 OpenSSL（本地命名管道不走 TLS）
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
    "qopensslbackend.dll", "qcertonlybackend.dll", "qschannelbackend.dll",
    # 只需要 ico 解码，其余图片插件全删
    "qgif.dll", "qicns.dll", "qjpeg.dll", "qpdf.dll", "qsvg.dll",
    "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll", "qsvgicon.dll",
    # 平台/其他插件
    "qdirect2d.dll", "qnetworklistmanager.dll",
    "qtvirtualkeyboardplugin.dll", "qtuiotouchplugin.dll",
}
# 按路径片段剔除：翻译与 Qml 运行时
DROP_PARTS = {"translations", "qml"}
# 只留简体中文语言包：QMessageBox / QFileDialog 的标准按钮要它才是中文
KEEP_NAMES = {"qtbase_zh_CN.qm"}


def _keep(entry) -> bool:
    path = Path(entry[0])
    if path.name in DROP_NAMES:
        return False
    if path.name in KEEP_NAMES:
        return True
    return not (DROP_PARTS & set(path.parts))


a = Analysis(
    [str(APP / "main.py")],
    pathex=[str(APP)],
    binaries=collect_dynamic_libs("hid"),
    datas=[],
    hiddenimports=["PySide6.QtNetwork"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtPdf",
        "PySide6.QtDesigner",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtPrintSupport",
        "PySide6.QtXml",
        "PySide6.QtDBus",
        "PySide6.QtOpenGL",
        "PySide6.QtSvg",
        "PySide6.QtPositioning",
        "PySide6.QtSerialPort",
        "PySide6.QtStateMachine",
        "PySide6.QtSensors",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtWebSockets",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtConcurrent",
        "PySide6.QtHelp",
        "PySide6.QtNetworkAuth",
    ],
    noarchive=False,
)

a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WirelessBattery",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WirelessBattery",
)
