# -*- coding: utf-8 -*-
"""主题与字体:THEMES→QSS(移植自 tkinter 版 _setup_ttk_style 的配色用法)。"""
from PySide6.QtGui import QFont

THEMES = {
    "橙黑": {
        "bg": "#0d0d0f", "panel": "#17171b", "line": "#2b2b32",
        "fg": "#f3f3f5", "sub": "#8b8b93", "accent": "#ff7a18", "on_accent": "#000000",
        "log_bg": "#0a0a0c", "log_fg": "#d8d8de",
        "ok": "#3ad07f", "warn": "#ffc24b", "err": "#ff5b5b",
        "log_gold": "#ffd700", "log_blue": "#4da6ff",
    },
    "绝区零": {
        "bg": "#101012", "panel": "#1b1b1f", "line": "#2f2f35",
        "fg": "#ffffff", "sub": "#8a8a8a", "accent": "#ffe200", "on_accent": "#000000",
        "log_bg": "#0b0b0d", "log_fg": "#e6e6e6",
        "ok": "#5be37a", "warn": "#ffd23f", "err": "#ff5252",
        "log_gold": "#ffd700", "log_blue": "#4da6ff",
    },
    "英伦": {
        "bg": "#0f2240", "panel": "#16304f", "line": "#27466e",
        "fg": "#f3ecd8", "sub": "#a8b4cc", "accent": "#d11a2a", "on_accent": "#ffffff",
        "log_bg": "#0b1a32", "log_fg": "#e8e2cf",
        "ok": "#5bc88a", "warn": "#e6b800", "err": "#ff6b6b",
        "log_gold": "#c9a227", "log_blue": "#7fb2ff",
    },
    "极简": {
        "bg": "#f5f5f4", "panel": "#ffffff", "line": "#d9d9d4",
        "fg": "#26261f", "sub": "#8b8b82", "accent": "#3a6ea5", "on_accent": "#ffffff",
        "log_bg": "#fafaf8", "log_fg": "#333330",
        "ok": "#1aa34a", "warn": "#c77700", "err": "#d83a3a",
        "log_gold": "#8a6d00", "log_blue": "#0066cc",
    },
}
DEFAULT_THEME = "橙黑"

FONT_SCALES = {"小": 0.9, "中": 1.0, "大": 1.15, "特大": 1.3}


def base_pt(size: int, settings: dict) -> int:
    """tkinter F(size) ≈ Qt point(size-1) × 字号档位,最小 8。"""
    scale = FONT_SCALES.get(settings.get("font_size", "中"), 1.0)
    return max(8, int(round((size - 1) * scale)))


def font(settings: dict, size: int, bold=False) -> QFont:
    f = QFont(settings.get("font_family", "微软雅黑"), base_pt(size, settings))
    f.setBold(bold)
    return f


def qss(theme_name: str, settings: dict) -> str:
    """全局 QSS。色值取自 THEMES,对照旧版 _setup_ttk_style:
    滚动条 trough=bg/thumb=line/hover=accent、下拉框 panel 底、
    进度条 trough=line/bar=accent、禁用态前景=sub。"""
    t = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    pt_small = base_pt(9, settings)
    return f"""
    QWidget {{
        background: {t['bg']}; color: {t['fg']};
        selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
    }}
    QWidget:disabled {{ color: {t['sub']}; }}
    QLabel {{ background: transparent; }}
    QFrame#sidebar {{ background: {t['panel']}; border-right: 1px solid {t['line']}; }}
    QFrame#runbar {{ background: {t['panel']}; border-top: 1px solid {t['line']}; }}

    /* ---- 输入类 ---- */
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t['panel']}; color: {t['fg']};
        border: 1px solid {t['line']}; border-radius: 4px; padding: 4px 6px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {t['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {t['sub']}; background: {t['bg']};
    }}
    QPlainTextEdit#logview {{ background: {t['log_bg']}; color: {t['log_fg']}; border: none; }}
    QPlainTextEdit#logview:focus {{ border: none; }}

    /* ---- 下拉框(含下拉列表与箭头,配色统一) ---- */
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox::down-arrow {{
        image: none; width: 0px; height: 0px;
        border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {t['sub']}; margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {t['panel']}; color: {t['fg']};
        border: 1px solid {t['line']}; outline: none;
        selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
    }}

    /* ---- 按钮:普通 / accent 变体 / danger 变体 / 侧栏导航 ---- */
    QPushButton {{
        background: {t['panel']}; color: {t['fg']};
        border: 1px solid {t['line']}; border-radius: 4px; padding: 5px 12px;
    }}
    QPushButton:hover {{ border-color: {t['accent']}; }}
    QPushButton[class="accent"] {{
        background: {t['accent']}; color: {t['on_accent']}; border: none; font-weight: bold;
    }}
    QPushButton[class="accent"]:hover {{ background: {t['accent']}; border: none; }}
    QPushButton[class="accent"]:disabled {{ background: {t['line']}; color: {t['sub']}; }}
    QPushButton[class="danger"] {{
        background: {t['err']}; color: #ffffff; border: none; font-weight: bold;
    }}
    QPushButton[class="danger"]:hover {{ background: {t['err']}; border: none; }}
    QPushButton[class="danger"]:disabled {{ background: {t['panel']}; color: {t['sub']}; }}
    QPushButton[class="nav"] {{
        background: transparent; color: {t['fg']}; border: none; border-radius: 6px;
        padding: 10px 12px; text-align: left;
    }}
    QPushButton[class="nav"]:hover {{ color: {t['accent']}; }}
    QPushButton[class="nav"][navActive="true"] {{ color: {t['accent']}; font-weight: bold; }}
    QPushButton:disabled {{
        color: {t['sub']}; background: {t['panel']}; border-color: {t['line']};
    }}
    QLabel[navActive="true"] {{ color: {t['accent']}; font-weight: bold; }}
    QWidget[navActive="true"] {{ color: {t['accent']}; }}

    /* ---- 复选框指示器 ---- */
    QCheckBox {{ background: transparent; spacing: 6px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px; border: 1px solid {t['line']};
        border-radius: 4px; background: {t['panel']};
    }}
    QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
    QCheckBox::indicator:disabled {{
        background: {t['bg']}; border-color: {t['line']};
    }}

    /* ---- 进度条(旧版 trough=line / bar=accent,thickness 7) ---- */
    QProgressBar {{
        background: {t['line']}; border: none; border-radius: 3px;
        min-height: 7px; max-height: 7px; text-align: center;
        color: transparent; font-size: 1px;
    }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}

    /* ---- 滚动条:细窄、无箭头、融入主题(竖向与横向都覆盖) ---- */
    QScrollBar:vertical {{
        background: {t['bg']}; width: 8px; border: none; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['line']}; border-radius: 4px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}
    QScrollBar:horizontal {{
        background: {t['bg']}; height: 8px; border: none; margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['line']}; border-radius: 4px; min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---- 分隔条:宽 6px,悬停高亮 ---- */
    QSplitter::handle {{ background: {t['line']}; }}
    QSplitter::handle:horizontal {{ width: 6px; }}
    QSplitter::handle:vertical {{ height: 6px; }}
    QSplitter::handle:hover {{ background: {t['accent']}; }}

    /* ---- 菜单 ---- */
    QMenu {{
        background: {t['panel']}; color: {t['fg']};
        border: 1px solid {t['line']}; padding: 4px;
    }}
    QMenu::item {{ padding: 5px 18px 5px 10px; border-radius: 4px; background: transparent; }}
    QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
    QMenu::item:disabled {{ color: {t['sub']}; }}
    QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 6px; }}

    QToolTip {{
        background: {t['panel']}; color: {t['fg']};
        border: 1px solid {t['accent']}; font-size: {pt_small}pt; padding: 3px 6px;
    }}
    """
