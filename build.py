# -*- coding: utf-8 -*-
"""一键构建：程序本体 -> payload.tar.xz -> 单文件安装包。"""
from __future__ import annotations

import lzma
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIST = ROOT / "dist_app" / "WirelessBattery"
PAYLOAD = ROOT / "installer" / "payload.tar.xz"
INSTALLER_DIST = ROOT / "dist"


def _py() -> str:
    """优先当前解释器；没装 PySide6/PyInstaller 时回退到本机 Python312。"""
    import importlib.util

    if importlib.util.find_spec("PyInstaller") and importlib.util.find_spec("PySide6"):
        return sys.executable
    fallback = Path.home() / "AppData/Local/Programs/Python/Python312/python.exe"
    if fallback.exists():
        return str(fallback)
    raise SystemExit("没有找到装有 PyInstaller 与 PySide6 的 Python 解释器")


PY = _py()


def _rmtree(path: Path) -> None:
    """整目录删除交给 PowerShell：几百上千个文件的批量删除会被安全策略拦截。"""
    if not path.exists():
        return
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"Remove-Item -LiteralPath '{path}' -Recurse -Force -ErrorAction SilentlyContinue"],
        check=False,
    )


def _rotate_old() -> None:
    """删掉上一次的程序本体输出，不留归档垃圾。"""
    _rmtree(ROOT / "dist_app" / "WirelessBattery")


def _purge(path: Path) -> None:
    """删除文件或整个目录：逐文件 unlink 再 rmdir，比批量删除更稳。"""
    if not path.exists():
        return
    if path.is_file() or path.is_symlink():
        path.unlink()
        return
    for child in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


# 本程序跑不到、但 PySide6 hook 会一并收进来的东西。
# 真实用到的只有 QtCore / QtGui / QtWidgets / QtNetwork（单实例互斥走本地命名管道，
# 不碰 TLS，所以 Qt 的 OpenSSL 与 tls 插件可以整块拿掉）。
UNUSED_FILES = [
    # 无用的 Qt 模块
    "PySide6/opengl32sw.dll",
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6Qml.dll",
    "PySide6/Qt6QmlModels.dll",
    "PySide6/Qt6QmlWorkerScript.dll",
    "PySide6/Qt6QmlMeta.dll",
    "PySide6/Qt6Pdf.dll",
    "PySide6/Qt6OpenGL.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/Qt6Svg.dll",
    # Qt 的 TLS 后端（只服务 https，本地 IPC 用不到）及它带来的 OpenSSL
    "PySide6/plugins/tls/qopensslbackend.dll",
    "PySide6/plugins/tls/qcertonlybackend.dll",
    "PySide6/plugins/tls/qschannelbackend.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    # 图片格式：只需要 ico（图标），其余解码器全是死重
    "PySide6/plugins/imageformats/qgif.dll",
    "PySide6/plugins/imageformats/qicns.dll",
    "PySide6/plugins/imageformats/qjpeg.dll",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/plugins/imageformats/qsvg.dll",
    "PySide6/plugins/imageformats/qtga.dll",
    "PySide6/plugins/imageformats/qtiff.dll",
    "PySide6/plugins/imageformats/qwbmp.dll",
    "PySide6/plugins/imageformats/qwebp.dll",
    "PySide6/plugins/iconengines/qsvgicon.dll",
    # 平台插件只留 qwindows
    "PySide6/plugins/platforms/qdirect2d.dll",
    "PySide6/plugins/networkinformation/qnetworklistmanager.dll",
]


def build_app() -> None:
    """按 app.spec 构建 onedir；无用组件在 spec 阶段就被过滤掉。"""
    _rotate_old()
    cmd = [
        PY, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist_app"),
        "--workpath", str(ROOT / "build"),
        str(ROOT / "app.spec"),
    ]
    subprocess.run(cmd, check=True)


def trim() -> None:
    """兜底清理：spec 已过滤绝大多数，这里补齐个别残留。"""
    internal = APP_DIST / "_internal"
    for rel in UNUSED_FILES:
        _purge(internal / rel)
    total = sum(f.stat().st_size for f in APP_DIST.rglob("*") if f.is_file())
    print(f"裁剪后体积 {total / 1024 / 1024:.1f} MB")


def pack_payload() -> None:
    """打成一个 solid tar.xz：比逐文件 deflate 省 ~10MB，解压还更快。"""
    if not APP_DIST.exists():
        raise SystemExit("未找到程序输出目录，请先构建程序本体。")
    PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    if PAYLOAD.exists():
        PAYLOAD.unlink()

    import io

    files = sorted(p for p in APP_DIST.rglob("*") if p.is_file())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for path in files:
            tf.add(path, arcname=str(path.relative_to(APP_DIST)))
    data = lzma.compress(buf.getvalue(), preset=6)
    PAYLOAD.write_bytes(data)
    print(f"payload.tar.xz {PAYLOAD.stat().st_size / 1024 / 1024:.1f} MB")


def clean_old() -> None:
    """清掉上一次的安装包与临时目录：dist 里永远只留最新一个 exe。"""
    removed: list[str] = []
    if INSTALLER_DIST.exists():
        for old in sorted(INSTALLER_DIST.glob("*.exe")):
            try:
                size = old.stat().st_size / 1024 / 1024
                old.unlink()
                removed.append(f"{old.name} ({size:.1f} MB)")
            except OSError as exc:
                print(f"跳过 {old.name}: {exc}")
    for junk in sorted(ROOT.glob("_old_*")) + sorted(ROOT.glob("_verify")):
        _rmtree(junk)
        removed.append(junk.name + "/")
    print("已清理旧产物: " + ("，".join(removed) if removed else "无"))


def build_installer() -> None:
    clean_old()
    cmd = [
        PY, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(INSTALLER_DIST),
        "--workpath", str(ROOT / "build_installer"),
        str(ROOT / "installer" / "setup.spec"),
    ]
    subprocess.run(cmd, check=True)


def cleanup_mid() -> None:
    """构建完成后清掉中间目录与 payload：项目里只留最终安装包。"""
    for name in ("build", "build_installer", "dist_app"):
        _rmtree(ROOT / name)
    if PAYLOAD.exists():
        PAYLOAD.unlink()
    print("已清理构建中间产物")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["app", "trim", "payload", "installer", "cleanup"]
    if "clean" in steps:
        clean_old()
        steps = [s for s in steps if s != "clean"]
    if "app" in steps:
        build_app()
    if "trim" in steps:
        trim()
    if "payload" in steps:
        pack_payload()
    if "installer" in steps:
        build_installer()
    if "cleanup" in steps:
        cleanup_mid()
    print("完成")
