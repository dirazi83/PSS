"""Theme: color palette + Qt style sheet.

Two palettes share one stylesheet template:
  * ``Palette``    — the default dark theme (used on Windows / Linux).
  * ``MacPalette`` — a modern macOS "Liquid Glass" look (translucent materials,
                     SF Pro, system-blue accent, hairline separators, rounder
                     corners). Applied only on macOS, from ``app.py``.

Only the QSS string is generated from these palettes. Colors consumed at runtime
by ``QColor`` (e.g. table status text) always read the base ``Palette`` hex
values, so ``MacPalette``'s ``rgba(...)`` tokens never reach ``QColor``.
"""

from __future__ import annotations


class Palette:
    """Central color palette so widgets stay consistent (default dark theme)."""

    bg = "#0f1117"          # window background
    surface = "#171a23"     # panels / cards
    surface_alt = "#1e222e"  # elevated rows / inputs
    border = "#2a2f3d"
    border_focus = "#5b6bff"

    text = "#e6e8ef"
    text_dim = "#9aa0b4"
    text_faint = "#6b7185"

    accent = "#6366f1"       # indigo
    accent_hover = "#7c7ff5"
    accent_press = "#5457d6"

    success = "#22c55e"
    warning = "#f59e0b"
    danger = "#ef4444"
    info = "#38bdf8"

    # ---- derived/extra tokens (Windows values match the original literals) ----
    font_stack = '"SF Pro Display", "Segoe UI", "Inter", system-ui, sans-serif'
    mono_stack = '"Menlo", "SF Mono", "JetBrains Mono", monospace'

    root_bg = bg
    header_bg = ("qlineargradient(x1:0 y1:0, x2:1 y2:0, "
                 "stop:0 #14172180, stop:1 #14172100)")

    # solid surfaces for top-level popups (dialogs, menus, dropdowns, tooltips)
    # which have no parent to composite a translucent fill against
    dialog_bg = bg
    popup_bg = surface_alt

    btn_bg = surface_alt
    btn_hover = "#232838"
    btn_press = "#2b3142"
    btn_disabled_bg = "#141722"
    primary_disabled_bg = "#353a52"
    primary_disabled_fg = "#8a8fb0"

    accent_soft = "rgba(99,102,241,0.18)"   # table selection
    accent_glow = "rgba(99,102,241,0.10)"   # row hover
    accent_wash = "rgba(99,102,241,0.08)"   # drop-zone active

    log_bg = "#0b0d13"

    r_card = "14px"
    r_btn = "10px"
    r_input = "9px"
    r_list = "12px"

    # status colors keyed by Job status name
    @classmethod
    def status_color(cls, status: str) -> str:
        return {
            "Queued": cls.text_faint,
            "Running": cls.info,
            "Done": cls.success,
            "Failed": cls.danger,
            "Skipped": cls.warning,
            "Stopped": cls.warning,
        }.get(status, cls.text_dim)


class MacPalette(Palette):
    """Modern macOS look — translucent glass materials, system-blue accent,
    hairline separators, SF Pro, rounder corners. QSS-only (see module docs)."""

    bg = "#1c1c1e"
    surface = "rgba(255,255,255,0.055)"      # frosted material
    surface_alt = "rgba(255,255,255,0.09)"   # elevated material
    border = "rgba(255,255,255,0.10)"        # hairline separator
    border_focus = "#0A84FF"

    text = "#f5f5f7"
    text_dim = "rgba(235,235,245,0.62)"      # macOS secondary label
    text_faint = "rgba(235,235,245,0.32)"    # macOS tertiary label

    accent = "#0A84FF"                        # macOS system blue (dark)
    accent_hover = "#409CFF"
    accent_press = "#0A6CD8"

    font_stack = ('"SF Pro Text", ".AppleSystemUIFont", -apple-system, '
                  '"Helvetica Neue", sans-serif')
    mono_stack = '"SF Mono", "Menlo", "JetBrains Mono", monospace'

    dialog_bg = "#1e1e20"     # solid popover/window material
    popup_bg = "#2c2c2e"

    root_bg = ("qlineargradient(x1:0 y1:0, x2:0 y2:1, "
               "stop:0 #26262b, stop:1 #161618)")
    header_bg = "rgba(255,255,255,0.05)"

    btn_bg = "rgba(255,255,255,0.09)"
    btn_hover = "rgba(255,255,255,0.14)"
    btn_press = "rgba(255,255,255,0.20)"
    btn_disabled_bg = "rgba(255,255,255,0.04)"
    primary_disabled_bg = "rgba(10,132,255,0.35)"
    primary_disabled_fg = "rgba(255,255,255,0.50)"

    accent_soft = "rgba(10,132,255,0.22)"
    accent_glow = "rgba(10,132,255,0.13)"
    accent_wash = "rgba(10,132,255,0.10)"

    log_bg = "rgba(0,0,0,0.28)"

    r_card = "16px"
    r_btn = "12px"
    r_input = "11px"
    r_list = "13px"


def stylesheet(p: type[Palette] = Palette) -> str:
    return f"""
    * {{
        font-family: {p.font_stack};
        font-size: 13px;
        color: {p.text};
        outline: none;
    }}

    QWidget#Root {{ background: {p.root_bg}; }}

    /* ---- Dialogs / message boxes ----
       Fusion gives top-level dialogs a near-white window background, which
       collides with the light default text color above and makes labels
       unreadable. Force the dark surface on every dialog so QLabel text,
       input dialogs, confirmations and the About box all read correctly. */
    QDialog {{ background: {p.dialog_bg}; color: {p.text}; }}
    QMessageBox {{ background: {p.dialog_bg}; color: {p.text}; }}
    QMessageBox QLabel {{ color: {p.text}; }}
    QInputDialog QLabel {{ color: {p.text}; }}

    /* ---- Header ---- */
    QFrame#Header {{
        background: {p.header_bg};
        border-bottom: 1px solid {p.border};
    }}
    QLabel#Title {{ font-size: 20px; font-weight: 700; color: {p.text}; }}
    QLabel#Subtitle {{ font-size: 12px; color: {p.text_dim}; }}
    QLabel#Brand {{
        font-size: 22px; font-weight: 800;
        color: {p.accent};
    }}

    /* ---- Cards / panels ---- */
    QFrame#Card, QFrame#Panel {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {p.r_card};
    }}
    QLabel#SectionTitle {{
        font-size: 12px; font-weight: 700; color: {p.text_dim};
        letter-spacing: 1px;
    }}

    /* ---- Buttons ---- */
    QPushButton {{
        background: {p.btn_bg};
        border: 1px solid {p.border};
        border-radius: {p.r_btn};
        padding: 8px 14px;
        color: {p.text};
        font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {p.border_focus}; background: {p.btn_hover}; }}
    QPushButton:pressed {{ background: {p.btn_press}; }}
    QPushButton:disabled {{ color: {p.text_faint}; background: {p.btn_disabled_bg}; border-color: {p.border}; }}

    QPushButton#Primary {{
        background: {p.accent}; border: none; color: white;
        padding: 10px 22px; font-size: 14px;
    }}
    QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {p.accent_press}; }}
    QPushButton#Primary:disabled {{ background: {p.primary_disabled_bg}; color: {p.primary_disabled_fg}; }}

    QPushButton#Danger {{ background: transparent; border: 1px solid {p.danger}; color: {p.danger}; }}
    QPushButton#Danger:hover {{ background: rgba(239,68,68,0.12); }}

    QPushButton#Ghost {{ background: transparent; border: 1px solid {p.border}; }}
    QPushButton#Ghost:hover {{ border-color: {p.border_focus}; }}

    /* ---- Inputs ---- */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {p.r_input};
        padding: 7px 10px;
        color: {p.text};
        selection-background-color: {p.accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.border_focus}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.popup_bg};
        border: 1px solid {p.border};
        border-radius: 8px;
        selection-background-color: {p.accent};
        padding: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

    /* ---- Checkboxes ---- */
    QCheckBox {{ spacing: 8px; color: {p.text}; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border-radius: 5px;
        border: 1px solid {p.border}; background: {p.surface_alt};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.border_focus}; }}
    QCheckBox::indicator:checked {{
        background: {p.accent}; border-color: {p.accent};
        image: none;
    }}

    /* ---- Slider ---- */
    QSlider::groove:horizontal {{ height: 6px; background: {p.surface_alt}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: white; width: 16px; height: 16px;
        margin: -6px 0; border-radius: 8px;
    }}

    /* ---- Table ---- */
    QTableWidget, QTableView {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {p.r_card};
        gridline-color: transparent;
        alternate-background-color: {p.surface_alt};
        selection-background-color: {p.accent_soft};
    }}
    QTableWidget::item, QTableView::item {{
        padding: 6px 8px; border-bottom: 1px solid {p.border};
    }}
    QTableWidget::item:hover, QTableView::item:hover {{
        background: {p.accent_glow};
    }}
    QStackedWidget {{ background: transparent; }}

    /* ---- List widgets (Site Manager, console detection results) ---- */
    QListWidget, QListView {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {p.r_list};
        alternate-background-color: {p.surface_alt};
        selection-background-color: {p.accent};
        selection-color: white;
        padding: 4px;
    }}
    QListWidget::item, QListView::item {{
        padding: 7px 10px; border-radius: 8px; color: {p.text};
    }}
    QListWidget::item:hover, QListView::item:hover {{
        background: {p.accent_glow};
    }}
    QListWidget::item:selected, QListView::item:selected {{
        background: {p.accent}; color: white;
    }}
    QListWidget::item:disabled, QListView::item:disabled {{ color: {p.text_faint}; }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: {p.r_list};
        top: -1px;
        background: {p.surface};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.text_dim};
        padding: 9px 18px;
        margin-right: 4px;
        border: 1px solid transparent;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        color: {p.text};
        background: {p.surface};
        border: 1px solid {p.border};
        border-bottom-color: {p.surface};
    }}
    QTabBar::tab:hover:!selected {{ color: {p.text}; }}

    /* ---- Primary navigation (top tabs): clean underline style ---- */
    QTabWidget#MainTabs {{ background: {p.root_bg}; }}
    QTabWidget#MainTabs::pane {{
        border: none;
        border-top: 1px solid {p.border};
        border-radius: 0;
        top: 0;
        background: transparent;
    }}
    QTabWidget#MainTabs > QTabBar {{ background: transparent; }}
    QTabWidget#MainTabs > QTabBar::tab {{
        background: transparent;
        color: {p.text_dim};
        font-size: 14px;
        font-weight: 600;
        padding: 13px 22px;
        margin: 0;
        border: none;
        border-bottom: 3px solid transparent;
        border-radius: 0;
    }}
    QTabWidget#MainTabs > QTabBar::tab:selected {{
        color: {p.text};
        background: transparent;
        border: none;
        border-bottom: 3px solid {p.accent};
    }}
    QTabWidget#MainTabs > QTabBar::tab:hover:!selected {{
        color: {p.text};
        border-bottom: 3px solid {p.border_focus};
    }}
    QLabel#BrandMark {{ background: transparent; }}

    /* ---- Cover art / status bar ---- */
    QLabel#Cover {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {p.r_list};
        color: {p.text_faint};
    }}
    QStatusBar#AppStatus {{
        background: {p.surface};
        color: {p.text_dim};
        border-top: 1px solid {p.border};
    }}

    /* ---- Empty-state drop zone ---- */
    QFrame#DropZone {{
        background: {p.surface};
        border: 2px dashed {p.border};
        border-radius: 16px;
    }}
    QFrame#DropZone[active="true"] {{
        border: 2px dashed {p.accent};
        background: {p.accent_wash};
    }}
    QLabel#DropIcon {{ font-size: 46px; color: {p.accent}; }}
    QLabel#DropHead {{ font-size: 17px; font-weight: 700; color: {p.text}; }}
    QLabel#DropSub {{ font-size: 13px; color: {p.text_faint}; }}
    QHeaderView::section {{
        background: {p.surface};
        color: {p.text_dim};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 10px 8px;
        font-weight: 700;
        font-size: 11px;
    }}
    QTableCornerButton::section {{ background: {p.surface}; border: none; }}

    /* ---- Progress bars ---- */
    QProgressBar {{
        background: {p.surface_alt};
        border: none; border-radius: 7px;
        height: 14px; text-align: center;
        color: {p.text}; font-size: 10px;
    }}
    QProgressBar::chunk {{
        border-radius: 7px;
        background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
            stop:0 {p.accent}, stop:1 {p.accent_hover});
    }}
    QProgressBar#Overall::chunk {{
        background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
            stop:0 {p.success}, stop:1 #4ade80);
    }}

    /* ---- Log ---- */
    QPlainTextEdit#Log {{
        background: {p.log_bg};
        border: 1px solid {p.border};
        border-radius: {p.r_list};
        font-family: {p.mono_stack};
        font-size: 12px;
        color: {p.text_dim};
        padding: 8px;
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 5px; min-width: 30px; }}

    QToolTip {{
        background: {p.popup_bg}; color: {p.text};
        border: 1px solid {p.border}; border-radius: 6px; padding: 5px 8px;
    }}

    /* ---- Menu bar + menus (esp. Windows, where the bar is in-window) ---- */
    QMenuBar {{
        background: {p.surface};
        color: {p.text};
        border-bottom: 1px solid {p.border};
        padding: 2px 6px;
    }}
    QMenuBar::item {{
        background: transparent;
        color: {p.text};
        padding: 6px 12px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{ background: {p.surface_alt}; color: {p.text}; }}
    QMenuBar::item:pressed {{ background: {p.accent}; color: white; }}
    QMenu {{
        background: {p.popup_bg};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{
        background: transparent;
        color: {p.text};
        padding: 6px 28px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{ background: {p.accent}; color: white; }}
    QMenu::item:disabled {{ color: {p.text_faint}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 6px 8px; }}
    QMenu::indicator {{ width: 16px; height: 16px; left: 6px; }}

    QLabel#VersionBadge {{
        background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
            stop:0 {p.accent}, stop:1 {p.accent_hover});
        color: white; font-weight: 800; font-size: 14px; letter-spacing: 2px;
        border-radius: 9px; padding: 8px 14px;
    }}

    QLabel#StatusBar {{ color: {p.text_dim}; font-size: 12px; }}
    QLabel#Pill {{
        background: {p.surface_alt}; border: 1px solid {p.border};
        border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;
    }}
    """
