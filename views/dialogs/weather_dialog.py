from PyQt6 import QtWidgets, QtCore

def _read_edited_values(original: dict, edits: dict) -> dict:
    """Relit les QLineEdit après édition manuelle, en essayant de préserver le type
    d'origine (int/float) de chaque valeur — repli sur la chaîne telle que saisie
    si la conversion échoue, plutôt que de bloquer l'application."""
    updated = {}
    for key, original_value in original.items():
        edit = edits.get(key)
        text = edit.text().strip() if edit else (str(original_value) if original_value is not None else "")
        if not text:
            updated[key] = None
            continue
        try:
            if isinstance(original_value, bool):
                updated[key] = text
            elif isinstance(original_value, int):
                updated[key] = int(text)
            elif isinstance(original_value, float):
                updated[key] = float(text.replace(",", "."))
            else:
                updated[key] = text
        except ValueError:
            updated[key] = text
    return updated


_FIELD_LABELS = {
    "airTemp": {"fr": "Température Air (°C)", "en": "Air Temperature (°C)"},
    "wind": {"fr": "Vent (Beaufort)", "en": "Wind (Beaufort)"},
    "wind_direction": {"fr": "Direction Vent", "en": "Wind Direction"},
    "weather": {"fr": "Météo (Ciel)", "en": "Weather"},
    "seaState": {"fr": "État de la Mer (Douglas)", "en": "Sea State (Douglas)"},
    "water_temperature": {"fr": "Température Eau (°C)", "en": "Water Temperature (°C)"},
    "swell_height": {"fr": "Hauteur Houle", "en": "Swell Height"},
    "swell_direction": {"fr": "Direction Houle", "en": "Swell Direction"},
}


class WeatherWebDialog(QtWidgets.QDialog):
    """Dialogue de comparaison des données météo web (Open-Meteo)."""

    def __init__(self, web_data: dict, lang: str = "fr", display_date: str = None,
                 on_apply=None, parent=None):
        """Initialise le dialogue avec les données météo web et la langue d'affichage."""
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window |
            QtCore.Qt.WindowType.WindowMaximizeButtonHint |
            QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.web_data = web_data
        self.lang = lang
        self.display_date = display_date
        self._on_apply = on_apply

        self.setWindowTitle(
            "Comparaison des Données Météo Web" if lang == "fr" else "Web Weather Data Comparison"
        )
        self.resize(450, 420)

        self.setStyleSheet("""
            QDialog { background-color: #111820; }
            QLabel { color: #b0c8d8; font-weight: bold; font-size: 12px;
                     font-family: "Segoe UI", sans-serif; }
            QLineEdit {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2a4057; border-radius: 4px;
                padding: 4px 8px; font-weight: bold; font-family: "Segoe UI", sans-serif;
            }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 6px 14px; font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
        """)

        self._setup_ui()

    def _setup_ui(self):
        """Construit le formulaire en lecture seule avec les champs météo traduits."""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        if self.display_date:
            header_text = (
                f"Données trouvées sur Open-Meteo pour le {self.display_date}"
                if self.lang == "fr"
                else f"Data resolved on Open-Meteo for {self.display_date}"
            )
        else:
            header_text = "Données trouvées sur Open-Meteo" if self.lang == "fr" else "Data captured on Open-Meteo"

        header_label = QtWidgets.QLabel(header_text)
        header_label.setStyleSheet(
            "font-size: 13px; color: #F2BFB4; border-bottom: 1px solid #2778A2; padding-bottom: 5px;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;")
        main_layout.addWidget(header_label)

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        self._field_edits: dict = {}
        for key, value in self.web_data.items():
            row_widget = QtWidgets.QWidget()
            h_layout = QtWidgets.QHBoxLayout(row_widget)
            h_layout.setContentsMargins(5, 2, 5, 2)
            h_layout.setSpacing(10)

            field_name = _FIELD_LABELS.get(key, {}).get(self.lang, key)
            field_label = QtWidgets.QLabel(field_name)
            field_label.setStyleSheet("min-width: 170px; border: none;")
            h_layout.addWidget(field_label, 1)

            line_edit = QtWidgets.QLineEdit()
            line_edit.setText(str(value) if value is not None else "")
            # Modifiable avant application : les valeurs Open-Meteo peuvent nécessiter
            # une correction manuelle (ex. relevé local plus précis) avant d'être écrites.
            self._field_edits[key] = line_edit
            h_layout.addWidget(line_edit, 2)

            form_layout.addWidget(row_widget)

        form_layout.addStretch()
        main_layout.addWidget(form_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        if self._on_apply:
            btn_apply = QtWidgets.QPushButton("Appliquer" if self.lang == "fr" else "Apply")
            btn_apply.setStyleSheet(
                "QPushButton{background:#1a5c2a;color:#c8f0d0;border:1px solid #2ea84a;"
                "border-radius:4px;padding:6px 14px;font-family:'Segoe UI',sans-serif;}"
                "QPushButton:hover{background:#2ea84a;}"
            )
            btn_apply.clicked.connect(self._apply)
            btn_layout.addWidget(btn_apply)

        btn_close = QtWidgets.QPushButton("Fermer" if self.lang == "fr" else "Close")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    def _apply(self):
        if not self._on_apply:
            return
        self._on_apply(_read_edited_values(self.web_data, self._field_edits))


class WeatherWebMultiDialog(QtWidgets.QDialog):
    """Dialogue de comparaison météo web pour plusieurs points sélectionnés à la fois.

    entries : liste de dicts {"video_path", "video_name", "date", "web_data"}.
    on_apply_one(web_data, video_path) est appelé pour appliquer un point donné.
    """

    def __init__(self, entries: list, lang: str = "fr", on_apply_one=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window |
            QtCore.Qt.WindowType.WindowMaximizeButtonHint |
            QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.entries = entries
        self.lang = lang
        self._on_apply_one = on_apply_one
        self._applied_paths: set = set()

        n = len(entries)
        self.setWindowTitle(
            f"Comparaison des Données Météo Web — {n} points" if lang == "fr"
            else f"Web Weather Data Comparison — {n} points"
        )
        self.resize(560, 560)

        self.setStyleSheet("""
            QDialog { background-color: #111820; }
            QLabel { color: #b0c8d8; font-weight: bold; font-size: 12px;
                     font-family: "Segoe UI", sans-serif; }
            QLineEdit {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2a4057; border-radius: 4px;
                padding: 4px 8px; font-weight: bold; font-family: "Segoe UI", sans-serif;
            }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 6px 14px; font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
            QGroupBox {
                border: 1px solid #2778A2; border-radius: 6px; margin-top: 10px;
                color: #F2BFB4; font-weight: bold; font-family: "Segoe UI", sans-serif;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QScrollArea { border: none; background: transparent; }
        """)

        self._setup_ui()

    def _t(self, fr: str, en: str) -> str:
        return fr if self.lang == 'fr' else en

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        header_label = QtWidgets.QLabel(self._t(
            f"Données trouvées sur Open-Meteo pour {len(self.entries)} points sélectionnés",
            f"Data resolved on Open-Meteo for {len(self.entries)} selected points"
        ))
        header_label.setStyleSheet(
            "font-size: 13px; color: #F2BFB4; border-bottom: 1px solid #2778A2; padding-bottom: 5px;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;")
        main_layout.addWidget(header_label)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        container.setStyleSheet("background: transparent;")
        entries_layout = QtWidgets.QVBoxLayout(container)
        entries_layout.setContentsMargins(0, 0, 0, 0)
        entries_layout.setSpacing(10)

        self._entry_widgets = []  # [(entry, btn_apply, group_box), ...]
        for entry in self.entries:
            grp, btn = self._build_entry_group(entry)
            self._entry_widgets.append((entry, btn, grp))
            entries_layout.addWidget(grp)
        entries_layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll, stretch=1)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_apply_all = QtWidgets.QPushButton(self._t("Tout appliquer", "Apply all"))
        btn_apply_all.setStyleSheet(
            "QPushButton{background:#1a5c2a;color:#c8f0d0;border:1px solid #2ea84a;"
            "border-radius:4px;padding:6px 14px;font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2ea84a;}"
        )
        btn_apply_all.clicked.connect(self._apply_all)
        btn_layout.addWidget(btn_apply_all)
        btn_layout.addStretch()
        btn_close = QtWidgets.QPushButton(self._t("Fermer", "Close"))
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    def _build_entry_group(self, entry: dict):
        web_data = entry.get("web_data") or {}
        title = entry.get("video_name", "")
        if entry.get("date"):
            title += f"  —  {entry['date']}"

        grp = QtWidgets.QGroupBox(title)
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        field_edits: dict = {}
        if not web_data:
            lbl_empty = QtWidgets.QLabel(self._t("Aucune donnée trouvée.", "No data found."))
            lbl_empty.setStyleSheet("color: #6a8fa8; font-weight: normal; border: none;")
            lay.addWidget(lbl_empty)
        else:
            for key, value in web_data.items():
                row_widget = QtWidgets.QWidget()
                h_layout = QtWidgets.QHBoxLayout(row_widget)
                h_layout.setContentsMargins(2, 0, 2, 0)
                h_layout.setSpacing(10)

                field_name = _FIELD_LABELS.get(key, {}).get(self.lang, key)
                field_label = QtWidgets.QLabel(field_name)
                field_label.setStyleSheet("min-width: 170px; border: none; font-weight: normal;")
                h_layout.addWidget(field_label, 1)

                line_edit = QtWidgets.QLineEdit()
                line_edit.setText(str(value) if value is not None else "")
                # Modifiable avant application (voir WeatherWebDialog._apply).
                field_edits[key] = line_edit
                h_layout.addWidget(line_edit, 2)

                lay.addWidget(row_widget)
        entry["_field_edits"] = field_edits

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_apply = QtWidgets.QPushButton(self._t("Appliquer à ce point", "Apply to this point"))
        btn_apply.setEnabled(bool(web_data) and self._on_apply_one is not None)
        btn_apply.clicked.connect(lambda: self._apply_one(entry, btn_apply, grp))
        btn_row.addWidget(btn_apply)
        lay.addLayout(btn_row)

        return grp, btn_apply

    def _apply_one(self, entry: dict, btn: QtWidgets.QPushButton, grp: QtWidgets.QGroupBox):
        if not self._on_apply_one:
            return
        video_path = entry.get("video_path")
        web_data = _read_edited_values(entry.get("web_data") or {}, entry.get("_field_edits") or {})
        self._on_apply_one(web_data, video_path)
        self._applied_paths.add(video_path)
        btn.setEnabled(False)
        btn.setText(self._t("✓ Appliqué", "✓ Applied"))
        grp.setStyleSheet("QGroupBox { border-color: #2ea84a; }")

    def _apply_all(self):
        if not self._on_apply_one:
            return
        for entry, btn, grp in self._entry_widgets:
            video_path = entry.get("video_path")
            if video_path in self._applied_paths or not entry.get("web_data"):
                continue
            self._apply_one(entry, btn, grp)
