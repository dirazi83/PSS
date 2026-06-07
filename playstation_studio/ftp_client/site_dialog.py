"""Site Manager dialog — add / edit / delete / duplicate FTP sites."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .ftp_detect import FtpDetectDialog, ftp_port_for
from .sites import HAVE_KEYRING, Site, SiteManager


class SiteManagerDialog(QDialog):
    def __init__(self, manager: SiteManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.selected_site: Site | None = None
        self.setWindowTitle("Site Manager")
        self.setMinimumSize(680, 460)

        root = QHBoxLayout(self)

        # left: list + list buttons
        left = QVBoxLayout()
        self.btn_detect = QPushButton("🔍  Detect PS4 / PS5…")
        self.btn_detect.setToolTip("Scan the network for consoles running an "
                                   "FTP server and add them as sites.")
        self.btn_detect.clicked.connect(self.on_detect)
        left.addWidget(self.btn_detect)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        left.addWidget(self.list, stretch=1)
        row = QHBoxLayout()
        for label, slot in (("Add", self.on_add), ("Duplicate", self.on_dup),
                            ("Delete", self.on_delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        left.addLayout(row)
        root.addLayout(left, stretch=1)

        # right: form
        self.form = self._build_form()
        root.addWidget(self.form, stretch=2)

        self._reload_list()

    def _build_form(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)

        self.f_name = QLineEdit()
        self.f_host = QLineEdit()
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_port.setValue(21)
        self.f_user = QLineEdit()
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.Password)
        self.f_anon = QCheckBox("Anonymous login")
        self.f_passive = QCheckBox("Passive mode")
        self.f_passive.setChecked(True)
        self.f_remote = QLineEdit("/")
        self.f_local = QLineEdit()
        self.f_fav = QCheckBox("Favorite")
        self.f_notes = QPlainTextEdit()
        self.f_notes.setFixedHeight(70)

        for label, field in (("Site name", self.f_name), ("Host", self.f_host),
                             ("Port", self.f_port), ("Username", self.f_user),
                             ("Password", self.f_pass)):
            lay.addWidget(QLabel(label))
            lay.addWidget(field)
        self.f_anon.toggled.connect(
            lambda on: (self.f_user.setDisabled(on), self.f_pass.setDisabled(on)))
        lay.addWidget(self.f_anon)
        lay.addWidget(self.f_passive)
        lay.addWidget(QLabel("Default remote directory"))
        lay.addWidget(self.f_remote)
        lay.addWidget(QLabel("Default local directory"))
        lay.addWidget(self.f_local)
        lay.addWidget(self.f_fav)
        lay.addWidget(QLabel("Notes"))
        lay.addWidget(self.f_notes)

        sec = QLabel("🔒 Passwords stored in your OS keyring."
                     if HAVE_KEYRING else
                     "⚠ keyring not installed — passwords saved in config "
                     "(run: pip install keyring).")
        sec.setWordWrap(True)
        sec.setStyleSheet("font-size:11px; color:#9aa0b4;")
        lay.addWidget(sec)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_save = QPushButton("Save")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self.on_save)
        b_conn = QPushButton("Save && Connect")
        b_conn.clicked.connect(self.on_save_connect)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_close)
        btns.addWidget(b_save)
        btns.addWidget(b_conn)
        lay.addLayout(btns)
        return w

    # ---- list ----
    def _reload_list(self, select: int = 0) -> None:
        self.list.clear()
        for s in self.manager.sites:
            star = "★ " if s.favorite else ""
            it = QListWidgetItem(f"{star}{s.name}")
            it.setData(Qt.UserRole, s.id)
            self.list.addItem(it)
        if self.manager.sites:
            self.list.setCurrentRow(min(select, len(self.manager.sites) - 1))

    def _current(self) -> Site | None:
        row = self.list.currentRow()
        if 0 <= row < len(self.manager.sites):
            return self.manager.sites[row]
        return None

    def _on_select(self, row: int) -> None:
        s = self._current()
        if not s:
            return
        self.f_name.setText(s.name)
        self.f_host.setText(s.host)
        self.f_port.setValue(s.port)
        self.f_user.setText(s.user)
        self.f_pass.setText(s.password)
        self.f_anon.setChecked(s.anonymous)
        self.f_passive.setChecked(s.passive)
        self.f_remote.setText(s.remote_dir)
        self.f_local.setText(s.local_dir)
        self.f_fav.setChecked(s.favorite)
        self.f_notes.setPlainText(s.notes)

    def _form_into(self, s: Site) -> None:
        s.name = self.f_name.text().strip() or "Unnamed"
        s.host = self.f_host.text().strip()
        s.port = self.f_port.value()
        s.user = self.f_user.text().strip()
        s.password = self.f_pass.text()
        s.anonymous = self.f_anon.isChecked()
        s.passive = self.f_passive.isChecked()
        s.remote_dir = self.f_remote.text().strip() or "/"
        s.local_dir = self.f_local.text().strip()
        s.favorite = self.f_fav.isChecked()
        s.notes = self.f_notes.toPlainText().strip()

    # ---- actions ----
    def on_add(self) -> None:
        self.manager.add(Site())
        self._reload_list(len(self.manager.sites) - 1)

    def on_detect(self) -> None:
        dlg = FtpDetectDialog(self)
        if not dlg.exec() or not dlg.chosen:
            return
        added = 0
        for console in dlg.chosen:
            ctype = console.get("type", "Console")
            cname = console.get("name", "")
            ip = console.get("ip", "")
            port = ftp_port_for(console) or 1337
            site = Site(
                name=f"{ctype} {ip}" if not cname else f"{ctype} · {cname}",
                host=ip, port=port,
                anonymous=True,        # console FTP servers usually need no login
                passive=True, remote_dir="/",
                notes=f"Auto-detected ({console.get('source', 'scan')}).")
            self.manager.add(site)
            added += 1
        self._reload_list(len(self.manager.sites) - 1)

    def on_dup(self) -> None:
        s = self._current()
        if s:
            self.manager.duplicate(s)
            self._reload_list(len(self.manager.sites) - 1)

    def on_delete(self) -> None:
        s = self._current()
        if s:
            self.manager.remove(s)
            self._reload_list()

    def on_save(self) -> None:
        s = self._current()
        if s:
            self._form_into(s)
            self.manager.update(s)
            self._reload_list(self.list.currentRow())

    def on_save_connect(self) -> None:
        self.on_save()
        self.selected_site = self._current()
        self.accept()
