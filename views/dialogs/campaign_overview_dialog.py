"""
Dialog "Vision globale campagne" : toutes les vidéos sur une timeline commune.

Ouverture via le bouton de la toolbar d'actions.
Clic sur une vidéo → signal video_selected(row_index).
"""

import os
import json

from PyQt6 import QtCore, QtGui, QtWidgets

from views.widgets.campaign_overview_widget import CampaignOverviewWidget
from services.campaign_service import get_video_json_path

_BTN_STYLE = """
    QToolButton {
        background-color: #162433; color: #a0c4d8;
        border: 1px solid #1e3448; border-radius: 4px;
        padding: 3px 12px; font-size: 11px;
    }
    QToolButton:hover { background-color: #1e3448; color: #d4e8f5; border-color: #2778A2; }
"""
_CLOSE_STYLE = """
    QPushButton {
        background-color: #162433; color: #a0c4d8;
        border: 1px solid #2778A2; border-radius: 4px;
        padding: 4px 18px; font-size: 11px;
    }
    QPushButton:hover { background-color: #2778A2; color: #ffffff; }
"""


class CampaignOverviewDialog(QtWidgets.QDialog):
    """Dialog non-modal affichant la vue globale de la campagne."""

    video_selected = QtCore.pyqtSignal(int)   # index dans video_model

    def __init__(self, campaign_folder: str, video_model: QtGui.QStandardItemModel,
                 parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window |
            QtCore.Qt.WindowType.WindowCloseButtonHint |
            QtCore.Qt.WindowType.WindowMaximizeButtonHint
        )
        name = os.path.basename(os.path.normpath(campaign_folder))
        self.setWindowTitle(f"Vision globale — {name}")
        self.setMinimumSize(900, 420)
        self.resize(1150, 560)
        self.setStyleSheet("QDialog { background-color: #0d1b2a; }")

        self._video_model = video_model
        entries = self._build_entries(video_model)
        self._overview = CampaignOverviewWidget(entries)

        self._build_ui(name, entries)

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self, campaign_name: str, entries: list):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header(campaign_name, entries))
        root.addWidget(self._make_scroll_area(), stretch=1)
        root.addWidget(self._make_footer())

    def _make_header(self, name: str, entries: list) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background-color: #111f2e; border-bottom: 1px solid #2778A2;")
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)

        lbl = QtWidgets.QLabel(f"Vision globale — {name}")
        lbl.setStyleSheet(
            "color: #F2BFB4; font-size: 14px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )
        lay.addWidget(lbl)

        # Stats rapides
        n = len(entries)
        validated = sum(1 for e in entries if e.get('exploitable') not in (None, '', '?'))
        total_s   = sum(e.get('duration_ms', 0) for e in entries) // 1000
        h, rem    = divmod(total_s, 3600)
        m, s      = divmod(rem, 60)
        dur_str   = f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"

        info = QtWidgets.QLabel(
            f"{n} vidéo{'s' if n != 1 else ''}  ·  {dur_str}  ·  {validated}/{n} exploitabilité définie"
        )
        info.setStyleSheet("color: #7ec8e3; font-size: 10px; margin-left: 16px;")
        lay.addWidget(info)
        lay.addStretch()

        # Légende exploitabilité
        for text, color in [
            ("Oui", "#4CAF50"), ("Non", "#D94F38"), ("Habitat", "#2778A2"),
            ("Communication", "#9B59B6"), ("?", "#F1C40F"), ("Non défini", "#3a4a5a"),
        ]:
            dot = QtWidgets.QLabel(f"● {text}")
            dot.setStyleSheet(f"color: {color}; font-size: 10px; margin-left: 6px;")
            lay.addWidget(dot)

        return w

    def _make_scroll_area(self) -> QtWidgets.QScrollArea:
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #0d1b2a; }"
        )
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(self._overview)
        self._overview.video_selected.connect(self.video_selected)
        return self._scroll

    def _make_footer(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background-color: #111f2e; border-top: 1px solid #1e3448;")
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(6)

        lbl = QtWidgets.QLabel("Zoom :")
        lbl.setStyleSheet("color: #7ec8e3; font-size: 10px;")
        lay.addWidget(lbl)

        def _tbtn(text, slot):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setStyleSheet(_BTN_STYLE)
            b.clicked.connect(slot)
            return b

        lay.addWidget(_tbtn("−",       lambda: self._overview.set_zoom(self._overview._zoom / 1.5)))
        lay.addWidget(_tbtn("Ajuster", self._fit))
        lay.addWidget(_tbtn("+",       lambda: self._overview.set_zoom(self._overview._zoom * 1.5)))

        hint = QtWidgets.QLabel("Molette : zoom  —  Clic sur une ligne : ouvrir la vidéo")
        hint.setStyleSheet("color: #3a5a72; font-size: 10px; margin-left: 14px;")
        lay.addWidget(hint)
        lay.addStretch()

        btn_close = QtWidgets.QPushButton("Fermer")
        btn_close.setStyleSheet(_CLOSE_STYLE)
        btn_close.clicked.connect(self.close)
        lay.addWidget(btn_close)

        return w

    # ── Helpers ───────────────────────────────────────────────────────────────

    def refresh(self, video_model: QtGui.QStandardItemModel):
        """Relit les JSONs et redessine le widget sans fermer ni changer le zoom."""
        self._video_model = video_model
        entries = self._build_entries(video_model)
        self._overview.update_entries(entries)

    def _refresh_on_show(self):
        if self._video_model is not None:
            self.refresh(self._video_model)

    def _fit(self):
        """Ajuste le zoom et la hauteur pour remplir tout l'espace disponible."""
        vw = self._scroll.viewport().width()
        vh = self._scroll.viewport().height()
        self._overview.fit_zoom(vw, min_height=vh)

    def showEvent(self, event):
        super().showEvent(event)
        # Ajuster et rafraîchir les données après affichage (viewport a sa taille réelle)
        QtCore.QTimer.singleShot(0, self._fit)
        # Si on ré-affiche un dialog caché, on rafraîchit depuis le modèle courant
        if self._video_model is not None:
            QtCore.QTimer.singleShot(50, self._refresh_on_show)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._fit)

    # ── Construction des données ──────────────────────────────────────────────

    def _build_entries(self, video_model: QtGui.QStandardItemModel) -> list:
        """Construit la liste d'entries à partir du QStandardItemModel partagé."""
        entries = []
        for row in range(video_model.rowCount()):
            name_item = video_model.item(row, 0)
            dur_item  = video_model.item(row, 1)
            if not name_item:
                continue

            path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            name = name_item.text()
            if not path:
                continue

            # Durée depuis la colonne 1 du modèle (format "MM:SS" déjà calculé)
            duration_ms = 0
            if dur_item:
                parts = dur_item.text().split(":")
                if len(parts) == 2:
                    try:
                        duration_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
                    except ValueError:
                        pass

            # Exploitabilité + événements depuis le JSON vidéo
            exploitable = None
            events: list[dict] = []
            json_path = get_video_json_path(path)
            if os.path.isfile(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    video_obs = data.get('video_observation', {})
                    exploitable = video_obs.get('exploitable', {}).get('value')
                    for key, ev_list in video_obs.items():
                        if not key.startswith('events_') or not isinstance(ev_list, list) or not ev_list:
                            continue
                        # Structure KOSMOS : ev_list = [{"values": [{frame_number_start, ...}, ...]}]
                        bucket = ev_list[0] if isinstance(ev_list[0], dict) else {}
                        for ev in bucket.get('values', []):
                            frame = ev.get('frame_number_start', 0)
                            # Approximation 25 fps (suffisant pour la vue globale)
                            events.append({'time_ms': int(frame * 1000 / 25), 'type': key})
                except Exception:
                    pass

            entries.append({
                'name':        name,
                'path':        path,
                'duration_ms': duration_ms,
                'exploitable': exploitable,
                'events':      events,
            })

        return entries
