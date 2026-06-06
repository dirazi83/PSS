"""Modern dark theme: color palette + Qt style sheet."""

from __future__ import annotations


class Palette:
    """Central color palette so widgets stay consistent."""

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


def stylesheet() -> str:
    p = Palette
    return f"""
    * {{
        font-family: "SF Pro Display", "Segoe UI", "Inter", system-ui, sans-serif;
        font-size: 13px;
        color: {p.text};
        outline: none;
    }}

    QWidget#Root {{ background: {p.bg}; }}

    /* ---- Header ---- */
    QFrame#Header {{
        background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
            stop:0 #14172180, stop:1 #14172100);
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
        border-radius: 14px;
    }}
    QLabel#SectionTitle {{
        font-size: 12px; font-weight: 700; color: {p.text_dim};
        letter-spacing: 1px;
    }}

    /* ---- Buttons ---- */
    QPushButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 8px 14px;
        color: {p.text};
        font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {p.border_focus}; background: #232838; }}
    QPushButton:pressed {{ background: #2b3142; }}
    QPushButton:disabled {{ color: {p.text_faint}; background: #141722; border-color: {p.border}; }}

    QPushButton#Primary {{
        background: {p.accent}; border: none; color: white;
        padding: 10px 22px; font-size: 14px;
    }}
    QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {p.accent_press}; }}
    QPushButton#Primary:disabled {{ background: #353a52; color: #8a8fb0; }}

    QPushButton#Danger {{ background: transparent; border: 1px solid {p.danger}; color: {p.danger}; }}
    QPushButton#Danger:hover {{ background: rgba(239,68,68,0.12); }}

    QPushButton#Ghost {{ background: transparent; border: 1px solid {p.border}; }}
    QPushButton#Ghost:hover {{ border-color: {p.border_focus}; }}

    /* ---- Inputs ---- */
    QLineEdit, QComboBox, QSpinBox {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 9px;
        padding: 7px 10px;
        selection-background-color: {p.accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p.border_focus}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.surface_alt};
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
        border-radius: 14px;
        gridline-color: transparent;
        alternate-background-color: {p.surface_alt};
        selection-background-color: rgba(99,102,241,0.18);
    }}
    QTableWidget::item, QTableView::item {{
        padding: 6px 8px; border-bottom: 1px solid {p.border};
    }}
    QTableWidget::item:hover, QTableView::item:hover {{
        background: rgba(99,102,241,0.10);
    }}
    QStackedWidget {{ background: transparent; }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 12px;
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
    QTabWidget#MainTabs {{ background: {p.bg}; }}
    QTabWidget#MainTabs::pane {{
        border: none;
        border-top: 1px solid {p.border};
        border-radius: 0;
        top: 0;
        background: {p.bg};
    }}
    QTabWidget#MainTabs > QTabBar {{ background: {p.bg}; }}
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
        border-radius: 12px;
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
        background: rgba(99,102,241,0.08);
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
        background: #0b0d13;
        border: 1px solid {p.border};
        border-radius: 12px;
        font-family: "Menlo", "SF Mono", "JetBrains Mono", monospace;
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
        background: {p.surface_alt}; color: {p.text};
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
        background: {p.surface_alt};
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
