"""Shared Help / Updates / About actions used by both window shells.

Decoupled from QMainWindow specifics (e.g. statusBar) via ``_notify_status`` so
the same code drives the classic shell and the Fluent shell.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog,
    QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import __version__ as APP_VERSION
from ..shared.assets import app_icon
from ..shared.config import CONFIG_DIR

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_README = os.path.join(_PROJECT_ROOT, "README.md")
_REPO_URL = "https://github.com/dirazi83/PSS"


class HelpActionsMixin:
    """Mixin providing Open-data-folder, Documentation, About and the in-app
    updater. Expects ``self`` to be a QWidget (used as dialog parent)."""

    # ----------------------------------------------------------- status hook
    def _notify_status(self, msg: str) -> None:
        sb = getattr(self, "statusBar", None)
        if callable(sb):
            try:
                sb().showMessage(msg)
            except Exception:        # pragma: no cover - shells without a bar
                pass

    # --------------------------------------------------------------- actions
    def _open_data_folder(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    def _show_docs(self) -> None:
        """Render README.md as HTML in an in-app viewer (not raw text)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("PlayStation Studio — Documentation")
        dlg.resize(900, 680)
        lay = QVBoxLayout(dlg)

        view = QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setSearchPaths([_PROJECT_ROOT])     # resolve relative images/links
        if os.path.isfile(_README):
            try:
                with open(_README, encoding="utf-8") as f:
                    view.setMarkdown(f.read())
            except OSError as e:
                view.setMarkdown(f"# Documentation\n\nCouldn't read README.md: {e}")
        else:
            view.setHtml(
                "<h2>Documentation</h2><p>Full docs on the project page: "
                f"<a href='{_REPO_URL}'>github.com/dirazi83/PSS</a></p>")
        lay.addWidget(view, 1)

        row = QHBoxLayout()
        btn_web = QPushButton("Open on GitHub")
        btn_web.setObjectName("Ghost")
        btn_web.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_REPO_URL + "#readme")))
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
        self._notify_status("Checking for updates…")
        self._upd_checker = UpdateChecker(APP_VERSION, self)
        self._upd_checker.done.connect(self._on_update_result)
        self._upd_checker.start()

    def _on_update_result(self, info: dict) -> None:
        from ..shared.updater import is_frozen
        self._notify_status("Ready")
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
