# -*- coding: utf-8 -*-
"""全局视觉规范：黑白双主题（运行时可切换，纯单色设计）。

设计原则
--------
1. 只有墨与纸两种极端，不引入任何彩色；层级靠灰度、字号与留白表达。
2. 不做"框中框"：卡片是一整块面，设备之间只用发丝线分隔，不画独立小卡片。
3. 数字是主角：电量百分比大号、加粗、对齐；说明性文字一律删掉。

样式表的组织
------------
`qss()` 由三段拼成，从广到窄，便于单独定位问题：
    基础段  卡片本体、标题、选项、发丝线、tooltip
    弹窗段  诊断页 / 添加设备：行、输入控件、滚动条、滚动区、消息框
    菜单段  托盘右键菜单
所有颜色都来自当前 _PALETTES，切主题后重新调用 qss() 即可整体换肤。
"""
from __future__ import annotations

MODES = ("dark", "light")
MODE_LABEL = {"dark": "深色", "light": "浅色"}

_PALETTES = {
    # 深色：近黑玻璃，白色墨迹
    "dark": {
        "BG":            "#0D0E10",
        "BG_SOFT":       "#16171A",
        "STROKE":        "rgba(255,255,255,0.075)",
        "STROKE_STRONG": "rgba(255,255,255,0.16)",
        "TEXT":          "#F4F5F7",
        "TEXT_SUB":      "#D5D8DE",
        "TEXT_DIM":      "#B7BCC4",
        "INK":           "#FFFFFF",
        "ON_INK":        "#0D0E10",
        "INK_SOFT":      "rgba(255,255,255,0.065)",
        "TRACK":         "rgba(255,255,255,0.10)",
        "HOVER":         "rgba(255,255,255,0.045)",
        # 毛玻璃：染色刻意压得薄，背后影像才透得出来
        "CARD_FILL":     "rgba(16,17,21,0.66)",
        "CARD_STROKE":   "rgba(255,255,255,0.16)",
        "CHIP_BG":       "rgba(255,255,255,0.06)",
        # 充电绿：单色体系里唯一的彩色，只用于"正在充电"这一状态。
        # 深色底上抬高亮度才不会发闷，浅色底上要压深才有对比。
        "CHARGE":        "#43D985",
        "CHARGE_DEEP":   "#12A85E",
        "CHARGE_TRACK":  "rgba(67,217,133,0.17)",
        "CHARGE_BOLT":   "#4CE08D",
    },
    # 浅色：纯白玻璃，黑色墨迹
    "light": {
        "BG":            "#FFFFFF",
        "BG_SOFT":       "#F5F5F7",
        "STROKE":        "rgba(0,0,0,0.11)",
        "STROKE_STRONG": "rgba(0,0,0,0.24)",
        "TEXT":          "#0A0B0C",
        "TEXT_SUB":      "#2A2E33",
        "TEXT_DIM":      "#3A4048",
        "INK":           "#0A0B0C",
        "ON_INK":        "#FFFFFF",
        "INK_SOFT":      "rgba(0,0,0,0.05)",
        "TRACK":         "rgba(0,0,0,0.085)",
        "HOVER":         "rgba(0,0,0,0.035)",
        # 霜化层用的"白"不能是纯白：卡片多半弹在浅色窗口上，纯白等于没有材质。
        # 这里压成带一点冷灰的白（≈ #EEF0F6），玻璃才会从白页面上"浮"出来
        # ——苹果的浅色材质在纯白背景下也是这个思路。
        "CARD_FILL":     "rgba(238,240,246,0.70)",
        # 白描边在白卡片上等于没有边框，浅色主题用淡墨线
        # 白玻璃上不需要粗墨线，真正的轮廓由内壁那道亮边给出（glasscard 里画）
        "CARD_STROKE":   "rgba(16,18,22,0.10)",
        # 玻璃更透了，选项框如果还完全透明就会糊进背景，给一层很薄的白垫底
        "CHIP_BG":       "rgba(255,255,255,0.36)",
        # 浅色底上 #43D985 会发灰发飘，压到 emerald 600 一带才立得住
        "CHARGE":        "#12A150",
        "CHARGE_DEEP":   "#0A7F3C",
        "CHARGE_TRACK":  "rgba(18,161,80,0.15)",
        "CHARGE_BOLT":   "#0E9C4A",
    },
}

_mode = "dark"

# 模块级颜色的占位：`from theme import TEXT` 这类引用在 _apply 之前也必须能导入。
# 真正的值由 _apply 从 _PALETTES 写进来。
BG = BG_SOFT = ""
STROKE = STROKE_STRONG = ""
TEXT = TEXT_SUB = TEXT_DIM = ""
INK = ON_INK = INK_SOFT = TRACK = HOVER = ""
CARD_FILL = CARD_STROKE = CHIP_BG = ""
CHARGE = CHARGE_DEEP = CHARGE_TRACK = CHARGE_BOLT = ""

FONT = "Microsoft YaHei UI"
FONT_NUM = "Segoe UI"


def current_mode() -> str:
    return _mode


def _apply(mode: str) -> None:
    global _mode
    if mode not in _PALETTES:
        mode = "dark"
    _mode = mode
    globals().update(_PALETTES[mode])


def set_mode(mode: str) -> str:
    _apply(mode)
    return _mode


# 托盘图标固定一种配色，不再跟随 Windows 深浅色 / 任务栏明暗。
# 之前按 SystemUsesLightTheme 取色（浅色任务栏→黑、深色→白），系统一换主题
# 图标就整体换色，观感很跳；用户明确要求"切深浅色不要改变托盘样式"，
# 所以这里收敛成常量。
# 墨色取黑：用户任务栏是浅米色，白图标在上面几乎看不见（已截图证实）。
TRAY_INK = "#0A0B0C"
# 浅底上的绿必须压深，亮绿 #43D985 在米色任务栏上会发飘
TRAY_CHARGE = "#0E9C4A"


def tray_icon_color() -> str:
    """托盘图标墨色：固定深黑。"""
    return TRAY_INK


def tray_charge_color() -> str:
    """充电态流动段的绿色：固定深绿。"""
    return TRAY_CHARGE


def color(css: str):
    """把样式表颜色（含 rgba(...)）转成 QColor。

    注意：QColor 不认 CSS 的 rgba() 字符串，直接构造会得到黑色。
    绘制代码必须统一走这里。
    """
    from PySide6.QtGui import QColor

    text = (css or "").strip()
    if text.startswith(("rgba(", "rgb(")):
        body = text[text.index("(") + 1: text.rindex(")")]
        parts = [p.strip() for p in body.split(",")]
        try:
            r = int(float(parts[0]))
            g = int(float(parts[1]))
            b = int(float(parts[2]))
            a = float(parts[3]) if len(parts) > 3 else 1.0
            if a <= 1.0:
                a *= 255
            return QColor(r, g, b, max(0, min(255, int(round(a)))))
        except Exception:
            return QColor(128, 128, 128)
    return QColor(text)


def ink_color():
    return color(INK)


def track_color():
    return color(TRACK)


def ink_soft_color():
    return color(INK_SOFT)


def hover_color():
    return color(HOVER)


def charge_color():
    return color(CHARGE)


def charge_deep_color():
    return color(CHARGE_DEEP)


def charge_track_color():
    return color(CHARGE_TRACK)


def charge_bolt_color():
    return color(CHARGE_BOLT)


# ---------------- 样式表 ----------------
def _base_qss() -> str:
    """卡片本体：标题、设备名、百分比、选项、发丝线。"""
    return f"""
    QWidget {{
        color: {TEXT};
        font-family: "{FONT}";
        font-size: 12px;
    }}
    #Card {{
        background: transparent;
        border: none;
    }}
    #HeaderLabel {{
        font-size: 12px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: 0.4px;
    }}
    #Empty {{
        font-size: 13px;
        color: {TEXT_SUB};
    }}
    #DevName {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    #SectionLabel {{
        font-size: 12px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: 0.4px;
    }}
    #SectionNote {{
        font-size: 12px;
        font-weight: 400;
        color: {TEXT_SUB};
        letter-spacing: 0px;
    }}
    #SwitchLabel {{
        font-size: 13px;
        color: {TEXT};
    }}
    QPushButton#Chip {{
        border: 1px solid {STROKE};
        border-radius: 8px;
        background: {CHIP_BG};
        color: {TEXT};
        font-size: 12px;
        padding: 3px 0px;
    }}
    QPushButton#Chip:hover {{
        border: 1px solid {STROKE_STRONG};
        color: {TEXT};
    }}
    QPushButton#Chip:checked {{
        background: {INK};
        border: 1px solid {INK};
        color: {ON_INK};
        font-weight: 600;
    }}
    QPushButton#Ghost {{
        border: none;
        border-radius: 8px;
        background: transparent;
        color: {TEXT};
        font-size: 12px;
        text-align: left;
        padding: 0px 2px;
    }}
    QPushButton#Ghost:hover {{
        color: {TEXT};
        background: {HOVER};
    }}
    QToolTip {{
        background: {BG_SOFT};
        color: {TEXT};
        border: 1px solid {STROKE_STRONG};
        padding: 6px 8px;
        border-radius: 8px;
        font-family: "{FONT}";
        font-size: 11px;
    }}
    """


def _dialog_qss() -> str:
    """独立窗口（诊断页 / 添加设备）：行、表单、滚动条、弹窗。

    只用 objectName 限定背景，不用 QWidget 通配：
    通配会把输入框和滚动区一起刷成窗口底色，边框和层级全糊掉。
    """
    return f"""
    #DiagRoot {{
        background: {BG};
    }}
    #DiagTitle {{
        font-size: 15px;
        font-weight: 700;
        color: {TEXT};
    }}
    #DiagStatus {{
        font-size: 12px;
        color: {TEXT_SUB};
    }}
    /* 诊断结果 / 接收器列表的一行：无框、无表头，靠留白分开 */
    #Row {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 10px;
    }}
    #PickRow {{
        background: {CHIP_BG};
        border: 1px solid {STROKE};
        border-radius: 10px;
    }}
    #PickRow:hover {{
        border: 1px solid {STROKE_STRONG};
    }}
    #PickRow[picked="true"] {{
        background: {INK_SOFT};
        border: 1px solid {INK};
    }}
    #RowName {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    #RowSub {{
        font-size: 11px;
        color: {TEXT_DIM};
    }}
    #RowState {{
        font-size: 12px;
        font-weight: 600;
        color: {TEXT_SUB};
    }}
    #RowStateDim {{
        font-size: 11px;
        color: {TEXT_DIM};
    }}
    #DiagEmpty {{
        font-size: 12px;
        color: {TEXT_DIM};
    }}
    /* 次要动作（添加设备 / 导出报告）：纯文字，不加框 */
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {TEXT_SUB};
        font-size: 12px;
        padding: 2px 4px;
        text-align: right;
    }}
    QPushButton#Link:hover {{
        color: {TEXT};
    }}
    /* 主操作按钮：诊断页只有这一个动作，用实心墨块顶在最显眼处 */
    QPushButton#Primary {{
        background: {INK};
        color: {ON_INK};
        border: none;
        border-radius: 9px;
        font-size: 12px;
        font-weight: 600;
        padding: 7px 18px;
    }}
    QPushButton#Primary:hover {{
        background: {TEXT_DIM};
        color: {ON_INK};
    }}
    QPushButton#Primary:disabled {{
        background: {INK_SOFT};
        color: {TEXT_SUB};
    }}
    /* 细进度条：只是告诉人"还在动"，不抢视线 */
    QProgressBar#DiagBar {{
        border: none;
        border-radius: 2px;
        background: {TRACK};
        max-height: 4px;
        min-height: 4px;
    }}
    QProgressBar#DiagBar::chunk {{
        border-radius: 2px;
        background: {INK};
    }}
    /* 输入控件必须有明确底色，否则就是"系统白底 + 主题白字"= 白底白字 */
    QLineEdit, QComboBox {{
        background: {BG_SOFT};
        border: 1px solid {STROKE};
        border-radius: 8px;
        padding: 6px 9px;
        color: {TEXT};
        placeholder-text-color: {TEXT_DIM};
        selection-background-color: {INK};
        selection-color: {ON_INK};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border: 1px solid {STROKE_STRONG};
    }}
    QLineEdit:disabled, QComboBox:disabled {{
        color: {TEXT_DIM};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background: {BG_SOFT};
        border: 1px solid {STROKE_STRONG};
        outline: none;
        color: {TEXT};
        selection-background-color: {HOVER};
        selection-color: {TEXT};
    }}

    /* 列表容器本身就是窗口底色，滚动区只负责滚动 —— 不画自己的框和底色 */
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {STROKE_STRONG};
        border-radius: 3px;
        min-height: 26px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {STROKE_STRONG};
        border-radius: 3px;
        min-width: 26px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
        width: 0px;
    }}

    /* 标准弹窗：不设底色在深色主题下同样是白底白字 */
    QMessageBox {{
        background: {BG};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
    }}
    QMessageBox QPushButton {{
        background: {BG_SOFT};
        border: 1px solid {STROKE_STRONG};
        border-radius: 8px;
        color: {TEXT};
        padding: 5px 16px;
        min-width: 62px;
    }}
    QMessageBox QPushButton:hover {{
        background: {HOVER};
    }}
    """


def menu_qss() -> str:
    """托盘菜单自己的样式。换肤时只刷菜单，不刷整份应用样式。"""
    return _menu_qss()


def _menu_qss() -> str:
    """托盘右键菜单。"""
    return f"""
    QMenu {{
        background: {BG_SOFT};
        color: {TEXT};
        border: 1px solid {STROKE_STRONG};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 22px 7px 14px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QMenu::item:selected {{
        background: {INK_SOFT};
        color: {TEXT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {STROKE};
        margin: 5px 8px;
    }}
    """


def qss() -> str:
    """完整样式表：基础 + 弹窗 + 菜单。"""
    return _base_qss() + _dialog_qss() + _menu_qss()


_apply("dark")
