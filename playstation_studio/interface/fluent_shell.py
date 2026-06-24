"""Fluent left-navigation shell (PySide6-Fluent-Widgets).

A FluentWindow with a left navigation rail listing the four sections. Used when
qfluentwidgets is importable; app.py falls back to the classic shell otherwise.
The section content widgets are the same functional tabs used by the classic
shell — only the chrome (window + navigation) changes.
"""

from __future__ import annotations

from qfluentwidgets import (
    FluentIcon as FIF, FluentWindow, NavigationItemPosition, Theme,
    setTheme, setThemeColor,
)

from .help_actions import HelpActionsMixin
from ..ftp_client.ftp_tab import FtpClientTab
from ..payload_sender.sender_tab import PayloadSenderTab
from ..ps4_manager.library_tab import Ps4LibraryTab
from ..ps5_compressor.compressor_tab import Ps5CompressTab
from ..shared.assets import app_icon
from ..shared.theme import Palette, stylesheet


def init_fluent_theme() -> None:
    """Apply the dark Fluent theme + accent. Must run *before* constructing the
    window — Fluent builds its chrome with whatever theme is active then."""
    setTheme(Theme.DARK)
    setThemeColor("#6366f1")               # app accent (indigo)


class FluentMainWindow(HelpActionsMixin, FluentWindow):
    """Top-level window with a Fluent left navigation rail."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PlayStation Studio")
        self.setWindowIcon(app_icon())
        self.resize(1200, 780)

        # The four section widgets. Each needs a unique objectName — FluentWindow
        # uses it as the navigation route key.
        self.ps4_tab = Ps4LibraryTab()
        self.ps4_tab.setObjectName("ps4Tab")
        self.ps5_tab = Ps5CompressTab()
        self.ps5_tab.setObjectName("ps5Tab")
        self.payload_tab = PayloadSenderTab()
        self.payload_tab.setObjectName("payloadTab")
        self.ftp_tab = FtpClientTab()
        self.ftp_tab.setObjectName("ftpTab")

        # Fluent themes the shell (nav rail / title bar / background). The
        # content widgets keep the app's own dark QSS, scoped per tab so it
        # doesn't clobber Fluent's app-level theme stylesheet.
        content_css = stylesheet(Palette)
        for tab in (self.ps4_tab, self.ps5_tab, self.payload_tab, self.ftp_tab):
            tab.setStyleSheet(content_css)

        self.addSubInterface(self.ps4_tab, FIF.GAME, "PKG Manager")
        self.addSubInterface(self.ps5_tab, FIF.ZIP_FOLDER, "PS5 Compressor")
        self.addSubInterface(self.payload_tab, FIF.SEND, "Payloads")
        self.addSubInterface(self.ftp_tab, FIF.GLOBE, "FTP Client")

        # Bottom of the rail: non-page actions (open a dialog, don't switch view).
        nav = self.navigationInterface
        nav.addItem("updates", FIF.UPDATE, "Check for Updates",
                    onClick=self._check_updates, selectable=False,
                    position=NavigationItemPosition.BOTTOM)
        nav.addItem("docs", FIF.HELP, "Documentation",
                    onClick=self._show_docs, selectable=False,
                    position=NavigationItemPosition.BOTTOM)
        nav.addItem("about", FIF.INFO, "About",
                    onClick=self._show_about, selectable=False,
                    position=NavigationItemPosition.BOTTOM)

        # Show the rail expanded (section labels visible) by default.
        nav.setMinimumExpandWidth(760)
        nav.expand(useAni=False)

    # ------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        for tab in (self.ps4_tab, self.ps5_tab, self.ftp_tab):
            tab.shutdown()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
