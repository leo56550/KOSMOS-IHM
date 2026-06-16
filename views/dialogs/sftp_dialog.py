import os
from PyQt6 import QtWidgets, QtCore, QtGui

from services.sftp_service import SftpConnectWorker, SftpDownloadWorker

_STYLE = """
QDialog {
    background-color: #111820;
    color: #ffffff;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
}
QGroupBox {
    border: 1px solid #2778A2;
    border-radius: 5px;
    margin-top: 18px;
    padding-top: 10px;
    color: #F2BFB4;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 3px 10px;
    background-color: #2778A2;
    color: white;
    border-radius: 3px;
    font-size: 12px;
}
QLabel {
    color: #b0c8d8;
    font-size: 11px;
    border: none;
}
QLineEdit {
    background-color: #162433;
    color: #F2BFB4;
    border: 1px solid #2a4057;
    border-radius: 3px;
    padding: 4px 7px;
    font-size: 11px;
}
QLineEdit:focus { border-color: #2778A2; }
QPushButton {
    background-color: #20415D;
    color: white;
    font-weight: bold;
    border: 1px solid #2778A2;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 11px;
}
QPushButton:hover { background-color: #2778A2; }
QPushButton:pressed { background-color: #152d42; }
QPushButton:disabled { color: #555; background-color: #1a1a1a; border-color: #333; }
QTreeWidget {
    background-color: #1b2c3d;
    color: #ffffff;
    border: 1px solid #2a4057;
    alternate-background-color: #111820;
    font-size: 11px;
}
QTreeWidget::item:selected { background-color: #2778A2; color: white; }
QTreeWidget::item:hover { background-color: #20415D; }
QHeaderView::section {
    background-color: #20415D;
    color: #F2BFB4;
    padding: 4px 8px;
    border: none;
    font-weight: bold;
    font-size: 11px;
}
QProgressBar {
    border: 1px solid #2a4057;
    border-radius: 3px;
    background-color: #162433;
    color: white;
    text-align: center;
    height: 16px;
    font-size: 10px;
}
QProgressBar::chunk {
    background-color: #2778A2;
    border-radius: 2px;
}
QScrollBar:vertical {
    width: 6px; background: transparent; margin: 0;
}
QScrollBar::handle:vertical {
    background: #2778A2; border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

_ICON_FOLDER = "📁"
_ICON_FILE   = "📄"


def _fmt_size(n_bytes: int) -> str:
    """Formate une taille en B/KB/MB/GB."""
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 ** 2:
        return f"{n_bytes / 1024:.1f} KB"
    if n_bytes < 1024 ** 3:
        return f"{n_bytes / 1024**2:.1f} MB"
    return f"{n_bytes / 1024**3:.2f} GB"


class SftpDialog(QtWidgets.QDialog):
    """Dialog de connexion SFTP au KOSMOS et de téléversement de la carte SD."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KOSMOS — Connexion SFTP / Carte SD")
        self.setModal(True)
        self.resize(780, 650)
        self.setStyleSheet(_STYLE)

        self._connect_worker: SftpConnectWorker | None = None
        self._download_worker: SftpDownloadWorker | None = None
        self._sftp_cfg: dict = {}          # ip, port, user, password, remote_dir
        self._local_dest: str = ""

        self._build_ui()
        self._set_connected(False)

    # ── Construction UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        root.addWidget(self._build_connection_group())
        root.addWidget(self._build_files_group(), stretch=1)
        root.addWidget(self._build_download_group())

        btn_close = QtWidgets.QPushButton("Fermer")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.reject)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        row.addWidget(btn_close)
        root.addLayout(row)

    def _build_connection_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox("Connexion SSH / SFTP")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(8)

        # Ligne 1 — identifiants
        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("Adresse IP :"))
        self.edit_ip = QtWidgets.QLineEdit("192.168.10.2")
        self.edit_ip.setFixedWidth(130)
        row1.addWidget(self.edit_ip)

        row1.addSpacing(10)
        row1.addWidget(QtWidgets.QLabel("Port :"))
        self.edit_port = QtWidgets.QLineEdit("22")
        self.edit_port.setFixedWidth(55)
        row1.addWidget(self.edit_port)

        row1.addSpacing(10)
        row1.addWidget(QtWidgets.QLabel("Utilisateur :"))
        self.edit_user = QtWidgets.QLineEdit("kosmos")
        self.edit_user.setFixedWidth(100)
        row1.addWidget(self.edit_user)

        row1.addSpacing(10)
        row1.addWidget(QtWidgets.QLabel("Mot de passe :"))
        self.edit_pwd = QtWidgets.QLineEdit("kosmos")
        self.edit_pwd.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.edit_pwd.setFixedWidth(100)
        row1.addWidget(self.edit_pwd)

        self.btn_show_pwd = QtWidgets.QPushButton("👁")
        self.btn_show_pwd.setFixedSize(28, 28)
        self.btn_show_pwd.setCheckable(True)
        self.btn_show_pwd.setToolTip("Afficher / masquer le mot de passe")
        self.btn_show_pwd.toggled.connect(self._toggle_pwd_visibility)
        row1.addWidget(self.btn_show_pwd)
        row1.addStretch()
        lay.addLayout(row1)

        # Ligne 2 — dossier distant + bouton connecter
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("Dossier distant :"))
        self.edit_remote = QtWidgets.QLineEdit("kosmos_local_sd")
        self.edit_remote.setPlaceholderText("Ex : kosmos_local_sd  ou  /home/kosmos/data")
        self.edit_remote.returnPressed.connect(self._on_refresh_remote)
        row2.addWidget(self.edit_remote)
        self.btn_refresh_remote = QtWidgets.QPushButton("Actualiser")
        self.btn_refresh_remote.setToolTip(
            "Relister le dossier distant (chemin modifiable même après connexion)")
        self.btn_refresh_remote.setMinimumWidth(90)
        self.btn_refresh_remote.setEnabled(False)
        self.btn_refresh_remote.clicked.connect(self._on_refresh_remote)
        row2.addWidget(self.btn_refresh_remote)
        self.btn_connect = QtWidgets.QPushButton("  Se connecter")
        self.btn_connect.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DriveNetIcon))
        self.btn_connect.setMinimumWidth(140)
        self.btn_connect.clicked.connect(self._on_connect)
        row2.addWidget(self.btn_connect)
        self.btn_disconnect = QtWidgets.QPushButton("Déconnecter")
        self.btn_disconnect.setMinimumWidth(110)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        row2.addWidget(self.btn_disconnect)
        lay.addLayout(row2)

        # Barre de progression connexion
        self.conn_progress = QtWidgets.QProgressBar()
        self.conn_progress.setRange(0, 0)   # mode indéterminé
        self.conn_progress.setVisible(False)
        self.conn_progress.setFixedHeight(14)
        lay.addWidget(self.conn_progress)

        # Statut connexion
        self.lbl_conn_status = QtWidgets.QLabel("")
        self.lbl_conn_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_conn_status)

        return grp

    def _build_files_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox("Fichiers distants")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(6)

        # Barre d'outils de sélection
        bar = QtWidgets.QHBoxLayout()
        self.lbl_file_count = QtWidgets.QLabel("—")
        bar.addWidget(self.lbl_file_count)
        bar.addStretch()
        self.btn_select_all = QtWidgets.QPushButton("Tout sélectionner")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_deselect_all = QtWidgets.QPushButton("Tout désélectionner")
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        bar.addWidget(self.btn_select_all)
        bar.addWidget(self.btn_deselect_all)
        lay.addLayout(bar)

        # Arbre de fichiers
        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setColumnCount(3)
        self.file_tree.setHeaderLabels(["Nom", "Taille", "Type"])
        self.file_tree.setColumnWidth(0, 380)
        self.file_tree.setColumnWidth(1, 90)
        self.file_tree.setColumnWidth(2, 80)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setAnimated(True)
        self.file_tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.file_tree)

        return grp

    def _build_download_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox("Téléversement vers l'ordinateur")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(8)

        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("Destination :"))
        self.edit_dest = QtWidgets.QLineEdit()
        self.edit_dest.setPlaceholderText("Choisir un dossier de destination…")
        self.edit_dest.setReadOnly(True)
        row1.addWidget(self.edit_dest)
        self.btn_browse = QtWidgets.QPushButton("Parcourir…")
        self.btn_browse.clicked.connect(self._browse_dest)
        row1.addWidget(self.btn_browse)
        lay.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        self.btn_download = QtWidgets.QPushButton("  Téléverser la sélection")
        self.btn_download.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowDown))
        self.btn_download.setMinimumWidth(200)
        self.btn_download.clicked.connect(self._on_download)
        row2.addWidget(self.btn_download)

        self.btn_cancel_dl = QtWidgets.QPushButton("Annuler")
        self.btn_cancel_dl.setVisible(False)
        self.btn_cancel_dl.clicked.connect(self._on_cancel_download)
        row2.addWidget(self.btn_cancel_dl)
        row2.addStretch()
        lay.addLayout(row2)

        self.dl_progress = QtWidgets.QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setValue(0)
        self.dl_progress.setVisible(False)
        self.dl_progress.setFixedHeight(16)
        lay.addWidget(self.dl_progress)

        self.lbl_dl_status = QtWidgets.QLabel("")
        self.lbl_dl_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_dl_status)

        return grp

    # ── État UI ───────────────────────────────────────────────────────────

    def _set_connected(self, connected: bool):
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.btn_refresh_remote.setEnabled(connected)
        self.btn_select_all.setEnabled(connected)
        self.btn_deselect_all.setEnabled(connected)
        self.btn_download.setEnabled(connected)
        self.btn_browse.setEnabled(connected)
        for field in [self.edit_ip, self.edit_port, self.edit_user, self.edit_pwd]:
            field.setEnabled(not connected)
        self.btn_show_pwd.setEnabled(not connected)

    # ── Connexion ─────────────────────────────────────────────────────────

    def _on_connect(self):
        ip = self.edit_ip.text().strip()
        user = self.edit_user.text().strip()
        pwd = self.edit_pwd.text()
        remote = self.edit_remote.text().strip()
        try:
            port = int(self.edit_port.text().strip())
        except ValueError:
            port = 22

        if not ip or not user or not remote:
            QtWidgets.QMessageBox.warning(self, "Champs manquants",
                                          "IP, utilisateur et dossier distant sont requis.")
            return

        self._sftp_cfg = dict(ip=ip, port=port, user=user, password=pwd,
                              remote_dir=remote)
        self.btn_connect.setEnabled(False)
        self.conn_progress.setVisible(True)
        self.lbl_conn_status.setText("Connexion en cours…")
        self.lbl_conn_status.setStyleSheet("color: #b0c8d8;")
        self.file_tree.clear()

        self._connect_worker = SftpConnectWorker(ip, port, user, pwd, remote)
        self._connect_worker.connected.connect(self._on_connected)
        self._connect_worker.error.connect(self._on_connect_error)
        self._connect_worker.start()

    def _on_connected(self, entries: list):
        self.conn_progress.setVisible(False)
        self.lbl_conn_status.setText(
            f"Connecté à {self._sftp_cfg['ip']} — {self.edit_remote.text()}")
        self.lbl_conn_status.setStyleSheet("color: #5ecf80; font-weight: bold;")
        self._set_connected(True)
        self._populate_tree(entries)

    def _on_connect_error(self, msg: str):
        self.conn_progress.setVisible(False)
        self.btn_connect.setEnabled(True)
        self.lbl_conn_status.setText(f"Erreur : {msg}")
        self.lbl_conn_status.setStyleSheet("color: #D94F38; font-weight: bold;")

    def _on_refresh_remote(self):
        """Reliste le dossier distant avec le chemin saisi, sans rouvrir la session credentials."""
        remote = self.edit_remote.text().strip()
        if not remote:
            return
        self._sftp_cfg['remote_dir'] = remote
        self.btn_refresh_remote.setEnabled(False)
        self.conn_progress.setVisible(True)
        self.lbl_conn_status.setText(f"Listage de {remote}…")
        self.lbl_conn_status.setStyleSheet("color: #b0c8d8;")
        self.file_tree.clear()

        cfg = self._sftp_cfg
        self._connect_worker = SftpConnectWorker(
            cfg['ip'], cfg['port'], cfg['user'], cfg['password'], remote)
        self._connect_worker.connected.connect(self._on_refreshed)
        self._connect_worker.error.connect(self._on_connect_error)
        self._connect_worker.start()

    def _on_refreshed(self, entries: list):
        self.conn_progress.setVisible(False)
        self.btn_refresh_remote.setEnabled(True)
        self.lbl_conn_status.setText(
            f"Connecté à {self._sftp_cfg['ip']} — {self.edit_remote.text()}")
        self.lbl_conn_status.setStyleSheet("color: #5ecf80; font-weight: bold;")
        self._populate_tree(entries)

    def _on_disconnect(self):
        if self._connect_worker and self._connect_worker.isRunning():
            self._connect_worker.requestInterruption()
        self.file_tree.clear()
        self.lbl_conn_status.setText("Déconnecté.")
        self.lbl_conn_status.setStyleSheet("color: #b0c8d8;")
        self.lbl_file_count.setText("—")
        self._set_connected(False)

    def _toggle_pwd_visibility(self, checked: bool):
        mode = (QtWidgets.QLineEdit.EchoMode.Normal if checked
                else QtWidgets.QLineEdit.EchoMode.Password)
        self.edit_pwd.setEchoMode(mode)

    # ── Arbre de fichiers ─────────────────────────────────────────────────

    def _populate_tree(self, entries: list):
        self.file_tree.blockSignals(True)
        self.file_tree.clear()
        total_files = [0]

        def add_items(parent_item, children):
            for entry in children:
                item = QtWidgets.QTreeWidgetItem(parent_item)
                icon = _ICON_FOLDER if entry['is_dir'] else _ICON_FILE
                item.setText(0, f"{icon}  {entry['name']}")
                item.setText(1, "" if entry['is_dir'] else _fmt_size(entry['size']))
                item.setText(2, "Dossier" if entry['is_dir'] else "Fichier")
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entry['path'])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, entry['is_dir'])
                flags = (QtCore.Qt.ItemFlag.ItemIsEnabled
                         | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                         | QtCore.Qt.ItemFlag.ItemIsAutoTristate)
                item.setFlags(flags)
                item.setCheckState(0, QtCore.Qt.CheckState.Checked)
                if entry['is_dir'] and entry['children']:
                    add_items(item, entry['children'])
                if not entry['is_dir']:
                    total_files[0] += 1

        add_items(self.file_tree.invisibleRootItem(), entries)
        self.file_tree.expandAll()
        self.file_tree.blockSignals(False)

        n = total_files[0]
        self.lbl_file_count.setText(f"{n} fichier{'s' if n > 1 else ''} trouvé{'s' if n > 1 else ''}")

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int):
        if column != 0:
            return
        # Cascade vers les enfants
        self.file_tree.blockSignals(True)
        self._propagate_check(item, item.checkState(0))
        self.file_tree.blockSignals(False)

    def _propagate_check(self, item: QtWidgets.QTreeWidgetItem,
                         state: QtCore.Qt.CheckState):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._propagate_check(child, state)

    def _select_all(self):
        self.file_tree.blockSignals(True)
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            self._propagate_check(item, QtCore.Qt.CheckState.Checked)
        self.file_tree.blockSignals(False)

    def _deselect_all(self):
        self.file_tree.blockSignals(True)
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
            self._propagate_check(item, QtCore.Qt.CheckState.Unchecked)
        self.file_tree.blockSignals(False)

    def _collect_selected_files(self) -> list:
        """Retourne la liste des chemins distants (fichiers uniquement) cochés."""
        result = []

        def walk(item):
            is_dir = item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1)
            state = item.checkState(0)
            if not is_dir and state != QtCore.Qt.CheckState.Unchecked:
                path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    result.append(path)
            for i in range(item.childCount()):
                walk(item.child(i))

        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))
        return result

    # ── Téléversement ─────────────────────────────────────────────────────

    def _browse_dest(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination", self._local_dest or "")
        if folder:
            self._local_dest = folder
            self.edit_dest.setText(folder)

    def _on_download(self):
        if not self._local_dest:
            QtWidgets.QMessageBox.warning(self, "Destination manquante",
                                          "Veuillez choisir un dossier de destination.")
            return

        files = self._collect_selected_files()
        if not files:
            QtWidgets.QMessageBox.information(self, "Rien à télécharger",
                                              "Aucun fichier sélectionné.")
            return

        remote_base = self._sftp_cfg.get('remote_dir', '').rstrip('/')
        cfg = self._sftp_cfg

        self.btn_download.setEnabled(False)
        self.btn_cancel_dl.setVisible(True)
        self.dl_progress.setVisible(True)
        self.dl_progress.setRange(0, len(files))
        self.dl_progress.setValue(0)
        self.lbl_dl_status.setStyleSheet("color: #b0c8d8;")
        self.lbl_dl_status.setText(f"Préparation — {len(files)} fichier(s) à télécharger…")

        self._download_worker = SftpDownloadWorker(
            cfg['ip'], cfg['port'], cfg['user'], cfg['password'],
            files, self._local_dest, remote_base
        )
        self._download_worker.progress.connect(self._on_dl_progress)
        self._download_worker.finished.connect(self._on_dl_finished)
        self._download_worker.error.connect(self._on_dl_error)
        self._download_worker.start()

    def _on_dl_progress(self, current: int, total: int, filename: str):
        self.dl_progress.setRange(0, total)
        self.dl_progress.setValue(current + 1)
        self.lbl_dl_status.setText(
            f"[{current + 1}/{total}]  {filename}")

    def _on_dl_finished(self, count: int):
        self.dl_progress.setValue(self.dl_progress.maximum())
        self.btn_download.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        self.lbl_dl_status.setStyleSheet("color: #5ecf80; font-weight: bold;")
        self.lbl_dl_status.setText(
            f"Terminé — {count} fichier{'s' if count > 1 else ''} téléchargé{'s' if count > 1 else ''}  ✓")

    def _on_dl_error(self, msg: str):
        self.btn_download.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        self.dl_progress.setVisible(False)
        self.lbl_dl_status.setStyleSheet("color: #D94F38; font-weight: bold;")
        self.lbl_dl_status.setText(f"Erreur : {msg}")

    def _on_cancel_download(self):
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.requestInterruption()
            self.btn_cancel_dl.setEnabled(False)
            self.lbl_dl_status.setText("Annulation en cours…")

    # ── Fermeture propre ──────────────────────────────────────────────────

    def closeEvent(self, event: QtGui.QCloseEvent):
        for w in [self._connect_worker, self._download_worker]:
            if w and w.isRunning():
                w.requestInterruption()
                w.wait(2000)
        super().closeEvent(event)

    def reject(self):
        self.closeEvent(QtGui.QCloseEvent())
        super().reject()
