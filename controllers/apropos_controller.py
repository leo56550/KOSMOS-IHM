import os

from PyQt6 import QtWidgets, QtCore, QtGui

APP_VERSION = "1.0.0"

_TECH_STACK = [
    ("PyQt6",        "Interface graphique — widgets, signaux/slots, MVC",
                      "Graphical interface — widgets, signals/slots, MVC"),
    ("OpenCV",       "Lecture vidéo, extraction de frames, traitement d'image",
                      "Video reading, frame extraction, image processing"),
    ("Matplotlib",   "Histogrammes, graphiques, export PDF",
                      "Histograms, charts, PDF export"),
    ("Folium",       "Carte interactive Leaflet (GPS tracks)",
                      "Interactive Leaflet map (GPS tracks)"),
    ("pandas",       "Lecture des fichiers CSV de télémétrie",
                      "Reading telemetry CSV files"),
    ("paramiko",     "Transfert SFTP depuis la carte SD KOSMOS",
                      "SFTP transfer from the KOSMOS SD card"),
    ("NumPy",        "Calculs vectorisés (histogramme, luminosité)",
                      "Vectorized computations (histogram, brightness)"),
]

_TEAM = [
    ("Léo Bultel",          "Développement logiciel, IMT Atlantique",
                             "Software development, IMT Atlantique"),
    ("Équipe KOSMOS",       "Conception système, IMT Atlantique",
                             "System design, IMT Atlantique"),
    ("Institut Mines-Télécom Atlantique", "Partenaire scientifique",
                                          "Scientific partner"),
]


class AProposController:
    """Contrôleur de la page À propos : contenu statique construit programmatiquement."""

    def __init__(self, widget: QtWidgets.QWidget, *args, **kwargs):
        self.widget = widget
        self.current_language = 'fr'
        self._build_ui()

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        self._build_ui()

    # ── Construction de l'UI ──────────────────────────────────────────────────

    def _build_ui(self):
        # Nettoie un éventuel layout résiduel du .ui
        old = self.widget.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(old)

        root_layout = QtWidgets.QVBoxLayout(self.widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QtWidgets.QWidget()
        container.setStyleSheet("background-color: #0d1b2a;")
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(0)

        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # ── Hero ─────────────────────────────────────────────────────────────
        layout.addLayout(self._make_hero())
        layout.addSpacing(36)

        # ── Description ──────────────────────────────────────────────────────
        layout.addWidget(self._section_title(self.translate("Présentation", "Overview")))
        layout.addSpacing(10)
        layout.addWidget(self._paragraph(self.translate(
            "KOSMOS IHM est l'interface de qualification et d'analyse des vidéos collectées "
            "par les robots sous-marins KOSMOS. Elle permet d'ouvrir une campagne, de visionner "
            "chaque vidéo, de saisir des métadonnées de terrain, d'annoter des événements biologiques "
            "sur la timeline, d'exporter des segments ou captures, et de générer un rapport de campagne.",
            "KOSMOS IHM is the interface for qualifying and analyzing videos collected "
            "by the KOSMOS underwater robots. It allows you to open a campaign, view "
            "each video, enter field metadata, annotate biological events "
            "on the timeline, export segments or captures, and generate a campaign report."
        )))
        layout.addSpacing(28)

        # ── Technologies ─────────────────────────────────────────────────────
        layout.addWidget(self._section_title("Technologies"))
        layout.addSpacing(10)
        layout.addWidget(self._tech_table())
        layout.addSpacing(28)

        # ── Équipe ───────────────────────────────────────────────────────────
        layout.addWidget(self._section_title(self.translate("Équipe & Institution", "Team & Institution")))
        layout.addSpacing(10)
        for name, role_fr, role_en in _TEAM:
            layout.addWidget(self._team_row(name, self.translate(role_fr, role_en)))
            layout.addSpacing(4)
        layout.addSpacing(28)

        # ── Licence & contact ─────────────────────────────────────────────────
        layout.addWidget(self._section_title(self.translate("Licence & Contact", "License & Contact")))
        layout.addSpacing(10)
        layout.addWidget(self._paragraph(self.translate(
            "Logiciel développé dans le cadre du projet KOSMOS — IMT Atlantique.\n"
            "Utilisation interne et scientifique.",
            "Software developed as part of the KOSMOS project — IMT Atlantique.\n"
            "Internal and scientific use."
        )))
        layout.addSpacing(28)

        # ── Pied de page ─────────────────────────────────────────────────────
        layout.addStretch()
        layout.addWidget(self._footer())

    def _make_hero(self) -> QtWidgets.QHBoxLayout:
        hero = QtWidgets.QHBoxLayout()
        hero.setSpacing(32)

        # Logo
        logo_path = os.path.join(
            os.path.dirname(__file__), '..', 'img', 'logo_kosmos.png'
        )
        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if os.path.isfile(logo_path):
            pix = QtGui.QPixmap(logo_path).scaledToHeight(
                110, QtCore.Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pix)
        else:
            logo_label.setText("KOSMOS")
            logo_label.setStyleSheet("color: #2778A2; font-size: 28px; font-weight: bold;")
        logo_label.setFixedWidth(180)

        # Titre + version
        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(6)

        lbl_title = QtWidgets.QLabel("KOSMOS IHM")
        lbl_title.setStyleSheet(
            "color: #F2BFB4; font-size: 30px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )

        lbl_sub = QtWidgets.QLabel(self.translate(
            "Interface de qualification des vidéos sous-marines",
            "Interface for qualifying underwater videos"
        ))
        lbl_sub.setStyleSheet(
            "color: #7ec8e3; font-size: 14px; font-family: 'Segoe UI', sans-serif;"
        )

        lbl_ver = QtWidgets.QLabel(f"Version {APP_VERSION}  —  IMT Atlantique")
        lbl_ver.setStyleSheet(
            "color: #5a7a8a; font-size: 11px; font-family: 'Segoe UI', sans-serif;"
        )

        title_col.addStretch()
        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        title_col.addSpacing(8)
        title_col.addWidget(lbl_ver)
        title_col.addStretch()

        hero.addWidget(logo_label)
        hero.addLayout(title_col)
        hero.addStretch()

        # Badge version (carré coloré)
        badge = self._version_badge()
        hero.addWidget(badge, alignment=QtCore.Qt.AlignmentFlag.AlignTop)

        return hero

    def _version_badge(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            "background-color: #162433; border: 1px solid #2778A2;"
            " border-radius: 8px; padding: 12px 18px;"
        )
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setSpacing(4)
        layout.setContentsMargins(16, 12, 16, 12)

        def _row(label, value, color="#d4e8f5"):
            h = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setStyleSheet("color: #5a7a8a; font-size: 10px; min-width: 70px;")
            val = QtWidgets.QLabel(value)
            val.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
            h.addWidget(lbl)
            h.addWidget(val)
            return h

        layout.addLayout(_row("Version", APP_VERSION, "#F2BFB4"))
        layout.addLayout(_row("PyQt6", "6.x"))
        layout.addLayout(_row("Python", "3.11+"))
        layout.addLayout(_row(self.translate("Plateforme", "Platform"), "Windows"))
        return frame

    def _section_title(self, text: str) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(
            "color: #F2BFB4; font-size: 16px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )
        layout.addWidget(lbl)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #2778A2; max-height: 1px; border: none;")
        layout.addWidget(line)
        return w

    def _paragraph(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "color: #a0c4d8; font-size: 12px; line-height: 1.6;"
            " font-family: 'Segoe UI', sans-serif;"
        )
        return lbl

    def _tech_table(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            "background-color: #0f2030; border: 1px solid #1e3448; border-radius: 6px;"
        )
        grid = QtWidgets.QGridLayout(frame)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(8)

        for row, (lib, desc_fr, desc_en) in enumerate(_TECH_STACK):
            lbl_lib = QtWidgets.QLabel(lib)
            lbl_lib.setStyleSheet(
                "color: #7ec8e3; font-weight: bold; font-size: 12px;"
                " font-family: 'Segoe UI', sans-serif; background: transparent;"
            )
            lbl_desc = QtWidgets.QLabel(self.translate(desc_fr, desc_en))
            lbl_desc.setStyleSheet(
                "color: #6a9ab0; font-size: 11px; font-family: 'Segoe UI', sans-serif;"
                " background: transparent;"
            )
            grid.addWidget(lbl_lib,  row, 0)
            grid.addWidget(lbl_desc, row, 1)

        grid.setColumnStretch(1, 1)
        return frame

    def _team_row(self, name: str, role: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet("background-color: transparent;")
        h = QtWidgets.QHBoxLayout(frame)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        dot = QtWidgets.QLabel("▸")
        dot.setStyleSheet("color: #2778A2; font-size: 13px;")
        dot.setFixedWidth(16)

        lbl_name = QtWidgets.QLabel(name)
        lbl_name.setStyleSheet(
            "color: #d4e8f5; font-weight: bold; font-size: 12px;"
            " font-family: 'Segoe UI', sans-serif;"
        )
        lbl_name.setFixedWidth(260)

        lbl_role = QtWidgets.QLabel(role)
        lbl_role.setStyleSheet(
            "color: #5a7a8a; font-size: 11px; font-family: 'Segoe UI', sans-serif;"
        )

        h.addWidget(dot)
        h.addWidget(lbl_name)
        h.addWidget(lbl_role)
        h.addStretch()
        return frame

    def _footer(self) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(
            "© 2025 Institut Mines-Télécom Atlantique — Projet KOSMOS"
        )
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: #2a4057; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
            " padding-top: 12px; border-top: 1px solid #1e3448;"
        )
        return lbl
