# -*- mode: python ; coding: utf-8 -*-
"""安装器打包配置。

命令行 --exclude-module 管不住 PySide6 的 hook（它会把整个 PySide6 目录的
DLL 全收进来），所以这里在 Analysis 之后、打包之前把 binaries/datas 过滤一遍。
安装器只有一个静态窗口：不需要 Qml/Quick/Pdf/OpenGL/Svg/Network，也不需要
任何 TLS 后端与 OpenSSL，更不需要 OpenGL 软件渲染兜底。
"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
INST = ROOT / "installer"

# 按文件名剔除（binaries 与 datas 都查）
DROP = {
    # 30MB 级的死重
    "opengl32sw.dll",
    "Qt6Quick.dll",
    "Qt6QuickControls2.dll",
    "Qt6Qml.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6QmlMeta.dll",
    "Qt6QuickWidgets.dll",
    "Qt6Pdf.dll",
    "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6Svg.dll",
    "Qt6Network.dll",
    # 包装模块
    "QtNetwork.pyd",
    "QtSvg.pyd",
    "QtPdf.pyd",
    "QtOpenGL.pyd",
    "QtQml.pyd",
    "QtQuick.pyd",
    # Qt 的 TLS + 它拉来的 OpenSSL（安装器不联网）
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "qopensslbackend.dll",
    "qcertonlybackend.dll",
    "qschannelbackend.dll",
    # 用不到的图片解码器（安装器只加载 ico/png）
    "qgif.dll",
    "qicns.dll",
    "qjpeg.dll",
    "qpdf.dll",
    "qsvg.dll",
    "qtga.dll",
    "qtiff.dll",
    "qwbmp.dll",
    "qwebp.dll",
    "qsvgicon.dll",
    # 其他插件
    "qdirect2d.dll",
    "qnetworklistmanager.dll",
    "qtvirtualkeyboardplugin.dll",
    "qtuiotouchplugin.dll",
}

a = Analysis(
    [str(INST / "setup.py")],
    pathex=[str(INST)],
    binaries=[],
    datas=[
        (str(INST / "payload.tar.xz"), "."),
        (str(ROOT / "assets" / "app.ico"), "."),
        (str(ROOT / "assets" / "box.png"), "."),
        (str(ROOT / "assets" / "check.png"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtPdf",
        "PySide6.QtOpenGL",
        "PySide6.QtSvg",
        "PySide6.QtMultimedia",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtPrintSupport",
        "PySide6.QtXml",
        "PySide6.QtDBus",
        "PySide6.QtCharts",
        "PySide6.Qt3DCore",
        "PySide6.QtDesigner",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    noarchive=False,
)


def _keep(entry):
    path = Path(entry[0])
    if path.name in DROP:
        return False
    if path.name == "qtbase_zh_CN.qm":      # 中文标签页/对话框按钮需要它
        return True
    if {"translations", "qml"} & set(path.parts):
        return False
    return True


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WirelessBatterySetup",
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
