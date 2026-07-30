from datetime import datetime

from PyQt6 import QtCore, QtWidgets

from services.recent_campaigns_service import load_recents, remove_recent_campaign

_LABEL_STYLE = "background: transparent; font-family: 'Segoe UI', sans-serif;"


class RecentCampaignsDialog(QtWidgets.QDialog):
    """Dialog listant les campagnes récentes et permettant d'en ouvrir une.

    Émet campaign_selected(campaign_folder, working_dir, derusher_name) sur validation.
    """

    campaign_selected = QtCore.pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ouvrir une campagne récente")
        self.setModal(True)
        self.setMinimumSize(720, 440)
        self.resize(860, 520)
        self.setStyleSheet("QDialog { background-color: #0d1b2a; }")

        self._recents = load_recents()
        self._build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_body(), stretch=1)
        root.addWidget(self._make_footer())

    def _make_header(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background-color: #111f2e; border-bottom: 1px solid #2778A2;")
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(16, 10, 16, 10)
        lbl = QtWidgets.QLabel("Campagnes récentes")
        lbl.setStyleSheet(
            "color: #F2BFB4; font-size: 14px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )
        lay.addWidget(lbl)
        lay.addStretch()
        count_lbl = QtWidgets.QLabel(f"{len(self._recents)} entrée(s)")
        count_lbl.setStyleSheet("color: #3a5568; font-size: 11px; font-family: 'Segoe UI', sans-serif;")
        lay.addWidget(count_lbl)
        return w

    def _make_body(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        container.setStyleSheet("background-color: #0d1b2a;")
        lay = QtWidgets.QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if not self._recents:
            empty = QtWidgets.QLabel("Aucune campagne récente")
            empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #3a5568; font-size: 13px; font-family: 'Segoe UI', sans-serif;")
            lay.addWidget(empty)
            self._list = None
            return container

        self._list = QtWidgets.QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background-color: #0d1b2a;
                border: none;
                outline: none;
            }
            QListWidget::item {
                border-bottom: 1px solid #1a2e40;
                padding: 0px;
            }
            QListWidget::item:selected {
                background-color: #162433;
            }
            QListWidget::item:hover:!selected {
                background-color: #0f2135;
            }
        """)
        self._list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.itemDoubleClicked.connect(self._open_selected)
        self._list.currentRowChanged.connect(self._on_row_changed)

        self._populate_list()
        lay.addWidget(self._list)
        return container

    def _make_footer(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background-color: #111f2e; border-top: 1px solid #1e3448;")
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)

        _base = (
            "QPushButton { background-color: #162433; color: #a0c4d8;"
            " border: 1px solid #1e3448; border-radius: 4px;"
            " padding: 5px 16px; font-size: 11px; font-family: 'Segoe UI', sans-serif; }"
            " QPushButton:hover { background-color: #1e3448; color: #d4e8f5; border-color: #2778A2; }"
            " QPushButton:disabled { color: #3a5568; border-color: #1a2e40; }"
        )
        _primary = (
            "QPushButton { background-color: #162433; color: #F2BFB4;"
            " border: 1px solid #2778A2; border-radius: 4px;"
            " padding: 5px 24px; font-size: 11px; font-weight: bold;"
            " font-family: 'Segoe UI', sans-serif; }"
            " QPushButton:hover { background-color: #2778A2; color: #ffffff; }"
            " QPushButton:disabled { color: #3a5568; border-color: #1a2e40; }"
        )

        self.btn_remove = QtWidgets.QPushButton("Retirer de la liste")
        self.btn_open   = QtWidgets.QPushButton("Ouvrir")
        btn_close       = QtWidgets.QPushButton("Fermer")

        self.btn_remove.setStyleSheet(_base)
        btn_close.setStyleSheet(_base)
        self.btn_open.setStyleSheet(_primary)

        self.btn_remove.setEnabled(False)
        self.btn_open.setEnabled(False)

        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_open.clicked.connect(self._open_selected)
        btn_close.clicked.connect(self.reject)

        lay.addWidget(self.btn_remove)
        lay.addStretch()
        lay.addWidget(btn_close)
        lay.addWidget(self.btn_open)
        return w

    # ── Peuplement de la liste ────────────────────────────────────────────────

    def _populate_list(self):
        if self._list is None:
            return
        self._list.clear()
        for entry in self._recents:
            item = QtWidgets.QListWidgetItem(self._list)
            widget = self._make_item_widget(entry)
            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

    def _make_item_widget(self, entry: dict) -> QtWidgets.QWidget:
        import os as _os
        w = QtWidgets.QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(3)

        name = entry.get('campaign_name') or _os.path.basename(
            _os.path.normpath(entry.get('campaign_folder', '—'))
        )
        raw   = entry.get('campaign_folder', '—')
        out   = entry.get('working_dir') or '—'
        derus = entry.get('derusher_name') or '—'
        iso   = entry.get('last_opened', '')
        try:
            opened = datetime.fromisoformat(iso).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            opened = iso or '—'

        name_lbl = QtWidgets.QLabel(name)
        name_lbl.setStyleSheet(
            _LABEL_STYLE + " color: #F2BFB4; font-size: 12px; font-weight: bold;"
        )

        raw_lbl = QtWidgets.QLabel(f"Dossier brut  :  {raw}")
        raw_lbl.setStyleSheet(_LABEL_STYLE + " color: #6a8fa8; font-size: 10px;")
        raw_lbl.setWordWrap(True)

        out_lbl = QtWidgets.QLabel(f"Dossier sortie :  {out}")
        out_lbl.setStyleSheet(_LABEL_STYLE + " color: #6a8fa8; font-size: 10px;")
        out_lbl.setWordWrap(True)

        meta_lbl = QtWidgets.QLabel(f"Dérusher : {derus}   •   Ouvert le : {opened}")
        meta_lbl.setStyleSheet(_LABEL_STYLE + " color: #3a5568; font-size: 10px;")

        lay.addWidget(name_lbl)
        lay.addWidget(raw_lbl)
        lay.addWidget(out_lbl)
        lay.addWidget(meta_lbl)
        return w

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_row_changed(self, row: int):
        ok = 0 <= row < len(self._recents)
        self.btn_open.setEnabled(ok)
        self.btn_remove.setEnabled(ok)

    def _open_selected(self):
        if self._list is None:
            return
        row = self._list.currentRow()
        if not (0 <= row < len(self._recents)):
            return
        e = self._recents[row]
        self.campaign_selected.emit(
            e.get('campaign_folder', ''),
            e.get('working_dir', ''),
            e.get('derusher_name', ''),
        )
        self.accept()

    def _remove_selected(self):
        if self._list is None:
            return
        row = self._list.currentRow()
        if not (0 <= row < len(self._recents)):
            return
        remove_recent_campaign(self._recents[row].get('campaign_folder', ''))
        self._recents.pop(row)
        self._populate_list()
        has = bool(self._recents)
        self.btn_open.setEnabled(False)
        self.btn_remove.setEnabled(False)
        if not has:
            self.btn_open.setEnabled(False)
            self.btn_remove.setEnabled(False)
