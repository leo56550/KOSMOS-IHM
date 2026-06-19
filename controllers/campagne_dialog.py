"""Dialog unique d'ouverture de campagne : dérusher + dossier campagne + répertoire de travail."""

import os
from PyQt6 import QtWidgets, QtCore, QtGui

_BASE_STYLE = """
    QDialog {
        background-color: #111820;
        color: #F2BFB4;
        font-family: 'Segoe UI', sans-serif;
    }
    QLabel {
        color: #7ec8e3;
        font-size: 11px;
        font-weight: bold;
        border: none;
    }
    QLabel#section_label {
        color: #F2BFB4;
        font-size: 12px;
        font-weight: bold;
        border: none;
    }
    QLineEdit {
        background-color: #162433;
        color: #F2BFB4;
        border: 1px solid #2778A2;
        border-radius: 4px;
        padding: 6px 8px;
        font-size: 12px;
    }
    QLineEdit:focus {
        border: 2px solid #4a9fcf;
    }
    QLineEdit[valid="false"] {
        border: 1px solid #c0392b;
    }
    QPushButton#browse_btn {
        background-color: #1a2f45;
        color: #7ec8e3;
        border: 1px solid #2778A2;
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 11px;
        min-width: 90px;
    }
    QPushButton#browse_btn:hover {
        background-color: #2778A2;
        color: #fff;
    }
    QPushButton#ok_btn {
        background-color: #20415D;
        color: white;
        font-weight: bold;
        border: 1px solid #2778A2;
        border-radius: 6px;
        padding: 9px 28px;
        font-size: 13px;
        min-width: 110px;
    }
    QPushButton#ok_btn:hover { background-color: #2778A2; }
    QPushButton#ok_btn:disabled { background-color: #1a2030; color: #555; border-color: #333; }
    QPushButton#cancel_btn {
        background-color: #1e1e2e;
        color: #7ec8e3;
        border: 1px solid #2a4057;
        border-radius: 6px;
        padding: 9px 22px;
        font-size: 13px;
        min-width: 90px;
    }
    QPushButton#cancel_btn:hover { background-color: #2a4057; }
    QFrame#sep {
        border: none;
        border-top: 1px solid #1e3448;
        max-height: 1px;
    }
"""


class CampagneDialog(QtWidgets.QDialog):
    """Dialog unique pour saisir le nom du dérusher, le dossier campagne et le répertoire de travail."""

    def __init__(self, parent=None, language: str = 'fr',
                 last_campaign: str = "", last_working_dir: str = ""):
        super().__init__(parent)
        self._lang = language
        self.setWindowTitle(self._t("Ouvrir une campagne", "Open campaign"))
        self.setMinimumWidth(540)
        self.setModal(True)
        self.setStyleSheet(_BASE_STYLE)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)

        # ── Titre ──────────────────────────────────────────────────────────
        title = QtWidgets.QLabel(self._t("Nouvelle session de dérushage", "New derushing session"))
        title.setObjectName("section_label")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        f = title.font()
        f.setPointSize(13)
        title.setFont(f)
        root.addWidget(title)

        root.addWidget(self._sep())

        # ── Nom du dérusher ────────────────────────────────────────────────
        root.addWidget(self._field_label(self._t("Nom du dérusher", "Derusher name")))
        self.edit_derusher = QtWidgets.QLineEdit()
        self.edit_derusher.setPlaceholderText(self._t("ex : Jean Dupont", "e.g. Jane Doe"))
        root.addWidget(self.edit_derusher)

        root.addWidget(self._sep())

        # ── Dossier campagne ───────────────────────────────────────────────
        root.addWidget(self._field_label(self._t("Dossier campagne", "Campaign folder")))
        campaign_row = QtWidgets.QHBoxLayout()
        campaign_row.setSpacing(8)
        self.edit_campaign = QtWidgets.QLineEdit()
        self.edit_campaign.setPlaceholderText(self._t(
            "Chemin vers le dossier source de la campagne",
            "Path to the campaign source folder"
        ))
        self.edit_campaign.setText(last_campaign)
        self.edit_campaign.setReadOnly(True)
        btn_campaign = QtWidgets.QPushButton(self._t("Parcourir…", "Browse…"))
        btn_campaign.setObjectName("browse_btn")
        btn_campaign.clicked.connect(self._browse_campaign)
        campaign_row.addWidget(self.edit_campaign)
        campaign_row.addWidget(btn_campaign)
        root.addLayout(campaign_row)

        root.addWidget(self._sep())

        # ── Répertoire de travail ──────────────────────────────────────────
        root.addWidget(self._field_label(
            self._t("Répertoire de travail (sorties IHM)", "Working directory (IHM outputs)")
        ))
        wd_row = QtWidgets.QHBoxLayout()
        wd_row.setSpacing(8)
        self.edit_wd = QtWidgets.QLineEdit()
        self.edit_wd.setPlaceholderText(self._t(
            "Dossier où seront copiés / enrichis les JSON vidéo",
            "Folder where video JSON files will be saved"
        ))
        self.edit_wd.setText(last_working_dir)
        self.edit_wd.setReadOnly(True)
        btn_wd = QtWidgets.QPushButton(self._t("Parcourir…", "Browse…"))
        btn_wd.setObjectName("browse_btn")
        btn_wd.clicked.connect(self._browse_working_dir)
        wd_row.addWidget(self.edit_wd)
        wd_row.addWidget(btn_wd)
        root.addLayout(wd_row)

        root.addSpacing(8)
        root.addWidget(self._sep())
        root.addSpacing(4)

        # ── Boutons OK / Annuler ───────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QtWidgets.QPushButton(self._t("Annuler", "Cancel"))
        self.btn_cancel.setObjectName("cancel_btn")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QtWidgets.QPushButton(self._t("Ouvrir", "Open"))
        self.btn_ok.setObjectName("ok_btn")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        root.addLayout(btn_row)

        # Live validation
        self.edit_derusher.textChanged.connect(self._refresh_ok)
        self._refresh_ok()

    # ── Helpers UI ──────────────────────────────────────────────────────────

    def _t(self, fr: str, en: str) -> str:
        return fr if self._lang == 'fr' else en

    def _field_label(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("section_label")
        return lbl

    def _sep(self) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("sep")
        f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        return f

    # ── Browse ──────────────────────────────────────────────────────────────

    def _browse_campaign(self):
        start = self.edit_campaign.text() or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self._t("Sélectionner le dossier campagne", "Select campaign folder"),
            start,
        )
        if folder:
            self.edit_campaign.setText(folder)
            # Proposer automatiquement un dossier de travail si pas encore défini
            if not self.edit_wd.text():
                default_wd = os.path.join(os.path.dirname(folder),
                                          os.path.basename(folder) + "_sortie_ihm")
                self.edit_wd.setText(default_wd)
            self._refresh_ok()

    def _browse_working_dir(self):
        start = self.edit_wd.text() or self.edit_campaign.text() or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self._t("Sélectionner le répertoire de travail", "Select working directory"),
            start,
        )
        if folder:
            self.edit_wd.setText(folder)
            self._refresh_ok()

    # ── Validation ──────────────────────────────────────────────────────────

    def _refresh_ok(self):
        ok = bool(
            self.edit_derusher.text().strip()
            and self.edit_campaign.text()
            and self.edit_wd.text()
        )
        self.btn_ok.setEnabled(ok)

    def _validate_and_accept(self):
        name = self.edit_derusher.text().strip()
        campaign = self.edit_campaign.text().strip()
        wd = self.edit_wd.text().strip()

        if not name:
            QtWidgets.QMessageBox.warning(self, self._t("Champ requis", "Required field"),
                                          self._t("Veuillez saisir un nom de dérusher.",
                                                  "Please enter a derusher name."))
            return
        if not os.path.isdir(campaign):
            QtWidgets.QMessageBox.warning(self, self._t("Dossier introuvable", "Folder not found"),
                                          self._t("Le dossier campagne sélectionné n'existe pas.",
                                                  "The selected campaign folder does not exist."))
            return
        if not os.path.isdir(wd):
            reply = QtWidgets.QMessageBox.question(
                self,
                self._t("Créer le répertoire ?", "Create directory?"),
                self._t(
                    f"Le répertoire de travail n'existe pas :\n{wd}\n\nVoulez-vous le créer ?",
                    f"The working directory does not exist:\n{wd}\n\nCreate it?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(wd, exist_ok=True)
                except OSError as e:
                    QtWidgets.QMessageBox.critical(self, "Erreur", str(e))
                    return
            else:
                return

        self.accept()

    # ── Résultats ───────────────────────────────────────────────────────────

    @property
    def derusher_name(self) -> str:
        return self.edit_derusher.text().strip()

    @property
    def campaign_folder(self) -> str:
        return self.edit_campaign.text().strip()

    @property
    def working_dir(self) -> str:
        return self.edit_wd.text().strip()
