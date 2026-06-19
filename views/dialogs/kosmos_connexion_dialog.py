"""Dialog hub 'KOSMOS Connexion' — point d'entrée SFTP et planification de déploiement."""

from PyQt6 import QtWidgets, QtCore, QtGui

_STYLE = """
QDialog {
    background-color: #111820;
    font-family: 'Segoe UI', sans-serif;
}
QLabel#title {
    color: #F2BFB4;
    font-size: 16px;
    font-weight: bold;
    border: none;
}
QLabel#subtitle {
    color: #7ec8e3;
    font-size: 11px;
    border: none;
}
QFrame#sep {
    border: none;
    border-top: 1px solid #1e3448;
    max-height: 1px;
}
"""

_CARD_STYLE = """
QPushButton {{
    background-color: {bg};
    color: {fg};
    border: 2px solid {border};
    border-radius: 10px;
    font-family: 'Segoe UI', sans-serif;
    font-weight: bold;
    font-size: 13px;
    padding: 20px 16px;
    text-align: left;
}}
QPushButton:hover {{
    background-color: {hover};
    border-color: {hover_border};
}}
QPushButton:pressed {{
    background-color: {pressed};
}}
"""


def _sep():
    f = QtWidgets.QFrame()
    f.setObjectName("sep")
    f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    return f


class KosmosConnexionDialog(QtWidgets.QDialog):
    """Landing dialog KOSMOS Connexion : SFTP ou Planification déploiement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KOSMOS Connexion")
        self.setModal(True)
        self.setFixedSize(480, 310)
        self.setStyleSheet(_STYLE)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        # ── Titre ──────────────────────────────────────────────────────────
        lbl_title = QtWidgets.QLabel("KOSMOS Connexion")
        lbl_title.setObjectName("title")
        lbl_sub = QtWidgets.QLabel("Choisissez une action")
        lbl_sub.setObjectName("subtitle")
        root.addWidget(lbl_title)
        root.addWidget(lbl_sub)
        root.addWidget(_sep())
        root.addSpacing(4)

        # ── Cartes d'action ────────────────────────────────────────────────
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(16)

        self.btn_sftp = self._card(
            "📡  Téléverser des vidéos",
            "Connexion SFTP à la Raspberry\net transfert de la carte SD",
            bg="#0d1f32", fg="#7ec8e3", border="#2778a2",
            hover="#162a3e", hover_border="#4a9fcf", pressed="#0a1520",
        )
        self.btn_plan = self._card(
            "🗺  Planifier un déploiement",
            "Poser des points sur la carte\net préparer les waypoints",
            bg="#1a1a0d", fg="#e6c86e", border="#8a7a20",
            hover="#252510", hover_border="#c9a83a", pressed="#111108",
        )

        cards.addWidget(self.btn_sftp)
        cards.addWidget(self.btn_plan)
        root.addLayout(cards, stretch=1)

        root.addWidget(_sep())

        btn_close = QtWidgets.QPushButton("Fermer")
        btn_close.setStyleSheet(
            "QPushButton { background-color: #1e1e2e; color: #7ec8e3;"
            " border: 1px solid #2a4057; border-radius: 6px; padding: 7px 20px;"
            " font-size: 12px; } QPushButton:hover { background-color: #2a4057; }"
        )
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.reject)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        row.addWidget(btn_close)
        root.addLayout(row)

        # Connexions
        self.btn_sftp.clicked.connect(self._open_sftp)
        self.btn_plan.clicked.connect(self._open_planner)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _card(title: str, desc: str, bg, fg, border, hover, hover_border, pressed) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(f"{title}\n\n{desc}")
        btn.setStyleSheet(_CARD_STYLE.format(
            bg=bg, fg=fg, border=border,
            hover=hover, hover_border=hover_border, pressed=pressed,
        ))
        btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        return btn

    # ── Actions ──────────────────────────────────────────────────────────────

    def _open_sftp(self):
        from views.dialogs.sftp_dialog import SftpDialog
        dlg = SftpDialog(self)
        dlg.exec()

    def _open_planner(self):
        from views.dialogs.deployment_planner_dialog import DeploymentPlannerDialog
        dlg = DeploymentPlannerDialog(self)
        dlg.exec()
