"""Dialog de planification de deploiement — carte Leaflet interactive + liste de waypoints."""

import json
import os
import sys
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel


def _resource(rel: str) -> str:
    """Chemin absolu d'un asset — compatible dev et PyInstaller (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.normpath(os.path.join(base, rel))


_MAP_HTML_PATH = _resource("assets/planner_map.html")

# ── Bridge Python <-> JS ─────────────────────────────────────────────────────

class _PlanBridge(QtCore.QObject):
    pointAdded = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot(str)
    def onPointAdded(self, payload: str):
        self.pointAdded.emit(payload)

# ── Styles ────────────────────────────────────────────────────────────────────

_STYLE = """
QDialog { background-color: #111820; font-family: 'Segoe UI', sans-serif; }
QLabel  { color: #7ec8e3; font-size: 11px; border: none; }
QLineEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QLineEdit:focus { border-color: #2778A2; }
QDateEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QDateEdit::drop-down { border: none; width: 18px; }
QDateEdit:focus { border-color: #2778A2; }
QListWidget {
    background-color: #0d1a27; color: #F2BFB4;
    border: 1px solid #1e3448; border-radius: 4px;
    font-size: 11px; outline: none;
}
QListWidget::item { padding: 7px 10px; border-bottom: 1px solid #1a2a38; }
QListWidget::item:selected { background-color: #20415D; color: #fff; }
QPushButton {
    background-color: #20415D; color: white; font-weight: bold;
    border: 1px solid #2778A2; border-radius: 4px;
    padding: 6px 14px; font-size: 11px;
}
QPushButton:hover { background-color: #2778A2; }
QPushButton#btn_delete { background-color: #3a1010; color: #e57373; border-color: #7a2020; }
QPushButton#btn_delete:hover { background-color: #7a2020; color: #fff; }
QPushButton#btn_clear  { background-color: #2a1a10; color: #e6a06e; border-color: #7a4010; }
QPushButton#btn_clear:hover  { background-color: #7a4010; color: #fff; }
QFrame#sep { border: none; border-top: 1px solid #1e3448; max-height: 1px; }
"""

def _lbl(text: str) -> QtWidgets.QLabel:
    l = QtWidgets.QLabel(text)
    l.setStyleSheet("color: #7ec8e3; font-size: 10px; border: none;")
    return l

def _sep() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("sep")
    f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    return f

# ── Dialog ────────────────────────────────────────────────────────────────────

class DeploymentPlannerDialog(QtWidgets.QDialog):
    """Dialog de planification : carte Leaflet + liste de waypoints nommables."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Planification de deploiement")
        self.setModal(True)
        self.resize(1150, 700)
        self.setStyleSheet(_STYLE)

        self._points: list[dict] = []
        self._updating_name = False   # garde contre boucle signal

        self._bridge  = _PlanBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("planBridge", self._bridge)
        self._bridge.pointAdded.connect(self._on_point_added)

        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Barre titre
        header = QtWidgets.QWidget()
        header.setStyleSheet("background-color: #0d1520; border-bottom: 1px solid #1e3448;")
        header.setFixedHeight(44)
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl_title = QtWidgets.QLabel("Planification de deploiement")
        lbl_title.setStyleSheet("color: #F2BFB4; font-size: 14px; font-weight: bold; border: none;")
        hl.addWidget(lbl_title)
        hl.addStretch()
        hl.addWidget(QtWidgets.QLabel("Cliquez sur la carte pour poser un waypoint"))
        root.addWidget(header)

        # Corps
        body = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        body.setHandleWidth(2)
        body.setStyleSheet("QSplitter::handle { background: #1e3448; }")

        # Carte
        self._map_view = QWebEngineView()
        self._map_view.page().setWebChannel(self._channel)
        self._map_view.setUrl(QtCore.QUrl.fromLocalFile(_MAP_HTML_PATH))
        body.addWidget(self._map_view)

        # ── Panneau droit ─────────────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #0d1520;")
        right.setMinimumWidth(250)
        right.setMaximumWidth(340)
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(14, 14, 14, 14)
        rl.setSpacing(8)

        # Nom de mission
        rl.addWidget(_lbl("Nom de la mission"))
        self._edit_mission = QtWidgets.QLineEdit()
        self._edit_mission.setPlaceholderText("ex : Campagne Iroise 2026")
        rl.addWidget(self._edit_mission)

        # Date de deploiement
        rl.addWidget(_lbl("Date de deploiement"))
        self._date_edit = QtWidgets.QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QtCore.QDate.currentDate())
        self._date_edit.setDisplayFormat("dd/MM/yyyy")
        rl.addWidget(self._date_edit)

        rl.addWidget(_sep())

        # Liste waypoints
        lbl_wp = QtWidgets.QLabel("Waypoints")
        lbl_wp.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 12px; border: none;")
        rl.addWidget(lbl_wp)

        self._list = QtWidgets.QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        rl.addWidget(self._list, stretch=1)

        # Edition du nom du point selectionne
        self._edit_name_lbl = _lbl("Nom du point selectionne")
        rl.addWidget(self._edit_name_lbl)
        self._edit_name = QtWidgets.QLineEdit()
        self._edit_name.setPlaceholderText("Nom du waypoint...")
        self._edit_name.setEnabled(False)
        self._edit_name.textEdited.connect(self._on_name_edited)
        rl.addWidget(self._edit_name)

        rl.addWidget(_sep())

        btn_del = QtWidgets.QPushButton("Supprimer la selection")
        btn_del.setObjectName("btn_delete")
        btn_del.clicked.connect(self._delete_selected)
        rl.addWidget(btn_del)

        btn_clr = QtWidgets.QPushButton("Tout effacer")
        btn_clr.setObjectName("btn_clear")
        btn_clr.clicked.connect(self._clear_all)
        rl.addWidget(btn_clr)

        rl.addWidget(_sep())

        btn_exp = QtWidgets.QPushButton("Exporter JSON")
        btn_exp.clicked.connect(self._export_json)
        rl.addWidget(btn_exp)

        btn_send = QtWidgets.QPushButton("Envoyer vers KOSMOS")
        btn_send.setStyleSheet(
            "QPushButton { background-color: #1a3a1a; color: #4CAF50;"
            " border: 1px solid #4CAF50; border-radius: 4px;"
            " padding: 6px 14px; font-size: 11px; font-weight: bold; }"
            " QPushButton:hover { background-color: #4CAF50; color: #fff; }"
        )
        btn_send.clicked.connect(self._send_to_kosmos)
        rl.addWidget(btn_send)

        body.addWidget(right)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        root.addWidget(body, stretch=1)

        # Pied de page
        footer = QtWidgets.QWidget()
        footer.setStyleSheet("background-color: #0d1520; border-top: 1px solid #1e3448;")
        footer.setFixedHeight(44)
        fl = QtWidgets.QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        self._lbl_count = QtWidgets.QLabel("0 waypoint(s)")
        self._lbl_count.setStyleSheet("color: #556677; font-size: 10px; border: none;")
        fl.addWidget(self._lbl_count)
        fl.addStretch()
        btn_close = QtWidgets.QPushButton("Fermer")
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.reject)
        fl.addWidget(btn_close)
        root.addWidget(footer)

    # ── Gestion des points ────────────────────────────────────────────────────

    def _on_point_added(self, payload: str):
        try:
            data = json.loads(payload)
        except Exception:
            return
        self._points.append({
            "label": data.get("label", f"Point {len(self._points)+1}"),
            "lat":   float(data["lat"]),
            "lng":   float(data["lng"]),
        })
        self._refresh_list()
        # Selectionner le nouveau point
        self._list.setCurrentRow(len(self._points) - 1)

    def _refresh_list(self):
        current = self._list.currentRow()
        self._list.clear()
        for i, p in enumerate(self._points):
            item = QtWidgets.QListWidgetItem(
                f"  {i+1}.  {p['label']}\n"
                f"       {p['lat']:.6f},  {p['lng']:.6f}"
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        n = len(self._points)
        self._lbl_count.setText(f"{n} waypoint{'s' if n != 1 else ''}")
        if 0 <= current < self._list.count():
            self._list.setCurrentRow(current)

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._points):
            self._edit_name.setEnabled(False)
            self._edit_name.clear()
            return
        self._edit_name.setEnabled(True)
        self._updating_name = True
        self._edit_name.setText(self._points[row]["label"])
        self._updating_name = False

    def _on_name_edited(self, text: str):
        if self._updating_name:
            return
        row = self._list.currentRow()
        if row < 0 or row >= len(self._points):
            return
        name = text.strip() or f"Point {row+1}"
        self._points[row]["label"] = name
        # Mettre a jour le marqueur JS
        safe = name.replace("'", "\\'")
        self._map_view.page().runJavaScript(f"updateMarkerLabel({row}, '{safe}');")
        # Mettre a jour l'item de la liste sans perdre le focus
        item = self._list.item(row)
        if item:
            item.setText(
                f"  {row+1}.  {name}\n"
                f"       {self._points[row]['lat']:.6f},  {self._points[row]['lng']:.6f}"
            )

    def _delete_selected(self):
        sel = self._list.selectedItems()
        if not sel:
            return
        idx = sel[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._map_view.page().runJavaScript(f"removeMarkerByIndex({idx});")
        del self._points[idx]
        self._edit_name.clear()
        self._edit_name.setEnabled(False)
        self._refresh_list()

    def _clear_all(self):
        if not self._points:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Confirmer", "Effacer tous les waypoints ?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._map_view.page().runJavaScript("clearAllMarkers();")
        self._points.clear()
        self._edit_name.clear()
        self._edit_name.setEnabled(False)
        self._refresh_list()

    # ── JSON payload (partagé entre export et envoi SFTP) ────────────────────

    def _build_json_bytes(self) -> bytes:
        payload = {
            "mission":          self._edit_mission.text().strip() or None,
            "date_deploiement": self._date_edit.date().toString("yyyy-MM-dd"),
            "waypoints": [
                {
                    "index":     i + 1,
                    "label":     p["label"],
                    "latitude":  round(p["lat"], 6),
                    "longitude": round(p["lng"], 6),
                }
                for i, p in enumerate(self._points)
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    # ── Export JSON local ─────────────────────────────────────────────────────

    def _export_json(self):
        if not self._points:
            QtWidgets.QMessageBox.information(self, "Export", "Aucun waypoint a exporter.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter le plan de deploiement",
            f"deploiement_{self._date_edit.date().toString('yyyyMMdd')}.json",
            "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, 'wb') as f:
                f.write(self._build_json_bytes())
            QtWidgets.QMessageBox.information(
                self, "Export reussi",
                f"{len(self._points)} waypoints exportes vers :\n{path}"
            )
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Erreur export", str(e))

    # ── Envoi SFTP vers KOSMOS ────────────────────────────────────────────────

    def _send_to_kosmos(self):
        if not self._points:
            QtWidgets.QMessageBox.information(self, "Envoi", "Aucun waypoint a envoyer.")
            return
        dlg = _SftpSendDialog(self._build_json_bytes(),
                              self._date_edit.date().toString("yyyyMMdd"),
                              parent=self)
        dlg.exec()


# ── Dialog d'envoi SFTP compact ──────────────────────────────────────────────

_SFTP_STYLE = """
QDialog { background-color: #111820; font-family: 'Segoe UI', sans-serif; }
QLabel  { color: #7ec8e3; font-size: 11px; border: none; }
QLineEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QLineEdit:focus { border-color: #2778A2; }
QPushButton {
    background-color: #20415D; color: white; font-weight: bold;
    border: 1px solid #2778A2; border-radius: 4px;
    padding: 6px 16px; font-size: 11px;
}
QPushButton:hover { background-color: #2778A2; }
QPushButton:disabled { background-color: #1a2030; color: #555; border-color: #333; }
QProgressBar {
    border: 1px solid #2778A2; border-radius: 3px;
    background-color: #0d1520; height: 10px; text-align: center;
}
QProgressBar::chunk { background-color: #4CAF50; border-radius: 2px; }
"""


class _SftpSendDialog(QtWidgets.QDialog):
    """Dialog compact pour envoyer un JSON de planification vers le KOSMOS en SFTP."""

    def __init__(self, data: bytes, date_str: str, parent=None):
        super().__init__(parent)
        self._data     = data
        self._date_str = date_str
        self._worker   = None

        self.setWindowTitle("Envoyer vers KOSMOS")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setStyleSheet(_SFTP_STYLE)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        # ── Connexion ─────────────────────────────────────────────────────
        def _row(label, widget):
            r = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFixedWidth(100)
            r.addWidget(lbl)
            r.addWidget(widget)
            root.addLayout(r)

        self._ip   = QtWidgets.QLineEdit("192.168.10.2")
        self._port = QtWidgets.QLineEdit("22")
        self._port.setFixedWidth(55)
        self._user = QtWidgets.QLineEdit("kosmos")
        self._pwd  = QtWidgets.QLineEdit("kosmos")
        self._pwd.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)

        _row("Adresse IP :", self._ip)
        _row("Port :", self._port)
        _row("Utilisateur :", self._user)
        _row("Mot de passe :", self._pwd)

        # Dossier distant
        self._remote_dir = QtWidgets.QLineEdit("/home/kosmos/deployments")
        _row("Dossier distant :", self._remote_dir)

        # ── Statut ────────────────────────────────────────────────────────
        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._lbl_status = QtWidgets.QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._lbl_status)

        # ── Boutons ───────────────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self._btn_send = QtWidgets.QPushButton("Envoyer")
        self._btn_send.setStyleSheet(
            "QPushButton { background-color: #1a3a1a; color: #4CAF50;"
            " border: 1px solid #4CAF50; border-radius: 4px;"
            " padding: 6px 20px; font-weight: bold; }"
            " QPushButton:hover { background-color: #4CAF50; color: #fff; }"
            " QPushButton:disabled { background-color: #1a2030; color: #555;"
            " border-color: #333; }"
        )
        self._btn_send.clicked.connect(self._do_send)
        btn_cancel = QtWidgets.QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_send)
        root.addLayout(btn_row)

    def _do_send(self):
        from services.sftp_service import SftpUploadWorker

        ip       = self._ip.text().strip()
        port     = int(self._port.text().strip() or "22")
        user     = self._user.text().strip()
        password = self._pwd.text()
        remote_dir = self._remote_dir.text().strip().rstrip('/')
        filename = f"deploiement_{self._date_str}.json"
        remote_path = f"{remote_dir}/{filename}"

        self._btn_send.setEnabled(False)
        self._progress.setVisible(True)
        self._lbl_status.setText("Connexion en cours…")
        self._lbl_status.setStyleSheet("color: #7ec8e3; font-size: 11px; border: none;")

        self._worker = SftpUploadWorker(ip, port, user, password, remote_path, self._data)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, remote_path: str):
        self._progress.setVisible(False)
        self._lbl_status.setText(f"Fichier envoye avec succes :\n{remote_path}")
        self._lbl_status.setStyleSheet("color: #4CAF50; font-size: 11px; border: none;")
        self._btn_send.setText("Fermer")
        self._btn_send.setEnabled(True)
        self._btn_send.clicked.disconnect()
        self._btn_send.clicked.connect(self.accept)

    def _on_error(self, msg: str):
        self._progress.setVisible(False)
        self._lbl_status.setText(f"Erreur : {msg}")
        self._lbl_status.setStyleSheet("color: #e57373; font-size: 11px; border: none;")
        self._btn_send.setEnabled(True)
