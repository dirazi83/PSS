"""Application shell: menu bar + icon-driven tab navigation + status bar."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QProgressDialog, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..ftp_client.ftp_tab import FtpClientTab
from ..payload_sender.sender_tab import PayloadSenderTab
from ..ps4_manager.library_tab import Ps4LibraryTab
from ..ps5_compressor.compressor_tab import Ps5CompressTab
from ..shared.assets import app_icon, make_icon
from ..shared.config import CONFIG_DIR

APP_VERSION = "1.0.4"
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
        act_docs.triggered.connect(self._show_docs)
        help_menu.addAction(act_docs)
        act_update = QAction("Check for Updates…", self)
        act_update.setMenuRole(QAction.NoRole)   # keep it in Help on all platforms
        act_update.triggered.connect(self._check_updates)
        help_menu.addAction(act_update)
        act_about = QAction("About PlayStation Studio", self)
        act_about.setMenuRole(QAction.AboutRole)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _open_data_folder(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    def _show_docs(self) -> None:
        """Render README.md as HTML in an in-app viewer (not raw text)."""
        from PySide6.QtWidgets import (
            QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("PlayStation Studio — Documentation")
        dlg.resize(900, 680)
        lay = QVBoxLayout(dlg)

        view = QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setSearchPaths([_PROJECT_ROOT])    # resolve relative images/links
        if os.path.isfile(_README):
            try:
                with open(_README, encoding="utf-8") as f:
                    view.setMarkdown(f.read())
            except OSError as e:
                view.setMarkdown(f"# Documentation\n\nCouldn't read README.md: {e}")
        else:
            view.setHtml(
                "<h2>Documentation</h2><p>Full docs on the project page: "
                "<a href='https://github.com/dirazi83/PSS'>"
                "github.com/dirazi83/PSS</a></p>")
        lay.addWidget(view, 1)

        row = QHBoxLayout()
        btn_web = QPushButton("Open on GitHub")
        btn_web.setObjectName("Ghost")
        btn_web.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/dirazi83/PSS#readme")))
        btn_close = QPushButton("Close")
        btn_close.setObjectName("Primary")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_web)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()

    def _show_about(self) -> None:
        """A rich HTML About panel with the app icon (not a plain text box)."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout)
        from ..ps5_compressor.jobs import mkpfs_version
        engine = mkpfs_version()
        engine_txt = f"MkPFS {engine}" if engine else "MkPFS"

        dlg = QDialog(self)
        dlg.setWindowTitle("About PlayStation Studio")
        dlg.setMinimumWidth(500)
        outer = QVBoxLayout(dlg)

        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(88, 88))
        icon.setAlignment(Qt.AlignTop)
        top.addWidget(icon)
        head = QLabel()
        head.setTextFormat(Qt.RichText)
        head.setOpenExternalLinks(True)
        head.setWordWrap(True)
        head.setText(
            "<h3 style='margin:0'>PlayStation Studio</h3>"
            f"<p style='margin:2px 0 10px 0; color:#9aa0b4'>Version {APP_VERSION}"
            "</p>"
            "<p>An all-in-one PS4/PS5 homebrew toolkit:</p>"
            "<ul style='margin-left:-20px'>"
            "<li><b>PKG Manager</b> — browse, rename, export, remote-install</li>"
            "<li><b>PS5 PFS Compressor</b> — batch game-dump compression</li>"
            "<li><b>Payload Sender</b> — send ELF/BIN/JAR over TCP</li>"
            "<li><b>FTP Client</b> — dual-pane transfers</li>"
            "</ul>")
        top.addWidget(head, 1)
        outer.addLayout(top)

        credits = QLabel()
        credits.setTextFormat(Qt.RichText)
        credits.setOpenExternalLinks(True)
        credits.setWordWrap(True)
        credits.setText(
            "<hr><p><b>Credits</b></p><ul style='margin-left:-20px'>"
            f"<li>PS5 compression engine: <b>{engine_txt}</b> by PSBrew — "
            "<a href='https://github.com/PSBrew/MkPFS'>github.com/PSBrew/MkPFS</a>"
            "</li>"
            "<li>Inspired by <b>PS5-FFPFSC-PRO</b> by KINGDKAK</li>"
            "<li>PS5 install: <b>etaHEN</b> DPI · PS4 install: "
            "<b>Remote PKG Installer</b> by flatz — "
            "<a href='https://github.com/flatz/ps4_remote_pkg_installer'>"
            "github.com/flatz/ps4_remote_pkg_installer</a></li>"
            "</ul><p style='color:#6b7185'>Built with Python &amp; PySide6.</p>")
        outer.addWidget(credits)

        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("OK")
        btn.setObjectName("Primary")
        btn.clicked.connect(dlg.accept)
        row.addWidget(btn)
        outer.addLayout(row)
        dlg.exec()

    # =============================================================== updates
    def _check_updates(self) -> None:
        from ..shared.updater import UpdateChecker
        if getattr(self, "_upd_checker", None) and self._upd_checker.isRunning():
            return
        self.statusBar().showMessage("Checking for updates…")
        self._upd_checker = UpdateChecker(APP_VERSION, self)
        self._upd_checker.done.connect(self._on_update_result)
        self._upd_checker.start()

    def _on_update_result(self, info: dict) -> None:
        from ..shared.updater import is_frozen
        self.statusBar().showMessage("Ready")
        if not info.get("ok"):
            QMessageBox.warning(
                self, "Check for Updates",
                f"Couldn't check for updates:\n{info.get('error', 'unknown error')}")
            return
        if not info.get("available"):
            QMessageBox.information(
                self, "Check for Updates",
                f"You're on the latest version (v{info['current']}).")
            return

        notes = (info.get("notes") or "").strip()
        if len(notes) > 1200:
            notes = notes[:1200].rstrip() + "\n…"
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>{info['latest']}</b> is available — "
                    f"you have v{info['current']}.")
        can_self = is_frozen() and bool(info.get("asset_url"))
        if not is_frozen():
            notes = ("You're running from source — use `git pull` to update.\n\n"
                     + notes)
        if notes:
            box.setInformativeText(notes)
        install_btn = (box.addButton("Download && Install", QMessageBox.AcceptRole)
                       if can_self else None)
        page_btn = box.addButton("Open Release Page", QMessageBox.ActionRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is page_btn:
            QDesktopServices.openUrl(QUrl(info["url"]))
        elif install_btn is not None and clicked is install_btn:
            self._download_update(info["asset_url"])

    def _download_update(self, asset_url: str) -> None:
        from ..shared.updater import UpdateInstaller
        self._upd_dialog = QProgressDialog(
            "Starting download…", "Cancel", 0, 100, self)
        self._upd_dialog.setWindowTitle("Updating PlayStation Studio")
        self._upd_dialog.setAutoClose(False)
        self._upd_dialog.setAutoReset(False)
        self._upd_dialog.setMinimumDuration(0)
        self._upd_installer = UpdateInstaller(asset_url, self)
        self._upd_installer.status.connect(self._upd_dialog.setLabelText)
        self._upd_installer.progress.connect(self._on_update_progress)
        self._upd_installer.ready.connect(self._on_update_ready)
        self._upd_installer.failed.connect(self._on_update_failed)
        self._upd_dialog.canceled.connect(self._upd_installer.cancel)
        self._upd_installer.start()
        self._upd_dialog.show()

    def _on_update_progress(self, pct: int) -> None:
        d = getattr(self, "_upd_dialog", None)
        if d is None:
            return
        if pct < 0:
            d.setRange(0, 0)          # indeterminate
        else:
            d.setRange(0, 100)
            d.setValue(pct)

    def _on_update_failed(self, msg: str) -> None:
        if getattr(self, "_upd_dialog", None):
            self._upd_dialog.close()
        QMessageBox.warning(self, "Update failed",
                            f"The update couldn't be installed:\n{msg}")

    def _on_update_ready(self, new_app: str) -> None:
        from ..shared.updater import apply_and_relaunch
        if getattr(self, "_upd_dialog", None):
            self._upd_dialog.close()
        resp = QMessageBox.question(
            self, "Restart to finish",
            "The update was downloaded. PlayStation Studio will close and "
            "reopen to apply it.\n\nRestart now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp != QMessageBox.Yes:
            return
        try:
            apply_and_relaunch(new_app)
        except (OSError, RuntimeError) as e:
            QMessageBox.warning(self, "Update failed", str(e))
            return
        QApplication.quit()         # the helper swaps the app, then relaunches

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
