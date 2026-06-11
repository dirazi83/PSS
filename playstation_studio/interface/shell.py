"""Application shell: menu bar + icon-driven tab navigation + status bar."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..ftp_client.ftp_tab import FtpClientTab
from ..payload_sender.sender_tab import PayloadSenderTab
from ..ps4_manager.library_tab import Ps4LibraryTab
from ..ps5_compressor.compressor_tab import Ps5CompressTab
from ..shared.assets import app_icon, make_icon
from ..shared.config import CONFIG_DIR

APP_VERSION = "1.0.0"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_README = os.path.join(_PROJECT_ROOT, "README.md")


class MainWindow(QMainWindow):
    """Top-level window. Menu bar + tab bar drive navigation."""

    TABS = [
        ("ps4", "PKG Manager", "PKG Manager"),
        ("ps5", "PS5  ·  PFS Compressor", "PS5 PFS Compressor"),
        ("payload", "Payloads", "Payload Sender"),
        ("ftp", "FTP Client", "FTP Client"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("PlayStation Studio")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(980, 600)

        central = QWidget()
        central.setObjectName("Root")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(22, 22))

        self.ps4_tab = Ps4LibraryTab()
        self.ps5_tab = Ps5CompressTab()
        self.payload_tab = PayloadSenderTab()
        self.ftp_tab = FtpClientTab()
        widgets = {"ps4": self.ps4_tab, "ps5": self.ps5_tab,
                   "payload": self.payload_tab, "ftp": self.ftp_tab}
        for key, label, _status in self.TABS:
            self.tabs.addTab(widgets[key], make_icon(key), label)
        # navigation lives in the View menu — hide the tab strip entirely
        self.tabs.tabBar().hide()
        root.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(central)
        self._build_menu()
        self.statusBar().setObjectName("AppStatus")
        self.statusBar().showMessage("Ready")
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # =============================================================== menu bar
    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        act_data = QAction("Open Data Folder", self)
        act_data.triggered.connect(self._open_data_folder)
        file_menu.addAction(act_data)
        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.setMenuRole(QAction.QuitRole)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = bar.addMenu("&View")
        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        self._view_actions: list[QAction] = []
        for i, (key, label, _status) in enumerate(self.TABS):
            act = QAction(make_icon(key), label.replace("  ·  ", " · "), self)
            act.setCheckable(True)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _=False, idx=i: self.tabs.setCurrentIndex(idx))
            self._view_group.addAction(act)
            view_menu.addAction(act)
            self._view_actions.append(act)
        self._view_actions[0].setChecked(True)

        help_menu = bar.addMenu("&Help")
        act_docs = QAction("Documentation", self)
        act_docs.setShortcut(QKeySequence.HelpContents)
        act_docs.triggered.connect(self._open_docs)
        help_menu.addAction(act_docs)
        act_about = QAction("About PlayStation Studio", self)
        act_about.setMenuRole(QAction.AboutRole)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _open_data_folder(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    def _open_docs(self) -> None:
        target = _README if os.path.isfile(_README) else _PROJECT_ROOT
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About PlayStation Studio",
            f"<h3>PlayStation Studio</h3>"
            f"<p>Version {APP_VERSION}</p>"
            "<p>An all-in-one toolkit:</p>"
            "<ul>"
            "<li><b>PKG Manager</b> — browse, rename, export, remote-install</li>"
            "<li><b>PS5 PFS Compressor</b> — batch game-dump compression</li>"
            "<li><b>Payload Sender</b> — send ELF/BIN/JAR over TCP</li>"
            "<li><b>FTP Client</b> — dual-pane transfers</li>"
            "</ul>"
            "<p style='color:#9aa0b4'>Built with Python &amp; PySide6.</p>"
            "<hr><p><b>Credits</b></p>"
            "<ul>"
            "<li>PS5 compression engine: <b>MkPFS</b> by PSBrew — "
            "<a href='https://github.com/PSBrew/MkPFS'>github.com/PSBrew/MkPFS</a></li>"
            "<li>Inspired by <b>PS5-FFPFSC-PRO</b> by KINGDKAK — "
            "<a href='https://github.com/KINGDKAK/PS5-FFPFSC-PRO'>"
            "github.com/KINGDKAK/PS5-FFPFSC-PRO</a></li>"
            "<li>PS5 install: <b>etaHEN</b> DPI · PS4 install: Remote PKG Installer</li>"
            "</ul>")

    # =============================================================== nav
    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self.TABS):
            self.statusBar().showMessage(self.TABS[index][2])
            if index < len(self._view_actions):
                self._view_actions[index].setChecked(True)

    def closeEvent(self, event) -> None:
        # stop background servers / threads cleanly
        self.ps4_tab.shutdown()
        self.ps5_tab.shutdown()
        self.ftp_tab.shutdown()
        super().closeEvent(event)
