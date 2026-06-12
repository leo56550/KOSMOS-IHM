from PyQt6 import QtWidgets


class WeatherWebDialog(QtWidgets.QDialog):
    """Dialogue de comparaison des données météo web (Open-Meteo)."""

    def __init__(self, web_data: dict, lang: str = "fr", display_date: str = None, parent=None):
        super().__init__(parent)
        self.web_data = web_data
        self.lang = lang
        self.display_date = display_date

        self.setWindowTitle(
            "Comparaison des Données Météo Web" if lang == "fr" else "Web Weather Data Comparison"
        )
        self.resize(450, 420)

        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; }
            QLabel { color: #ccc; font-weight: bold; font-size: 12px; }
            QLineEdit {
                background-color: #2b2b2b; color: #00ffaa;
                border: 1px solid #555; border-radius: 4px; padding: 4px; font-weight: bold;
            }
            QPushButton {
                background-color: #3a3a3a; color: white;
                border: 1px solid #555; border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a4a4a; border-color: #00ffaa; }
        """)

        self._setup_ui()

    def _setup_ui(self):
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
        header_label.setStyleSheet("font-size: 13px; color: #00ffaa; border-bottom: 2px solid #555; padding-bottom: 5px;")
        main_layout.addWidget(header_label)

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        translation_labels = {
            "airTemp": {"fr": "Température Air (°C)", "en": "Air Temperature (°C)"},
            "wind": {"fr": "Vent (Beaufort)", "en": "Wind (Beaufort)"},
            "wind_direction": {"fr": "Direction Vent", "en": "Wind Direction"},
            "weather": {"fr": "Météo (Ciel)", "en": "Weather"},
            "seaState": {"fr": "État de la Mer (Douglas)", "en": "Sea State (Douglas)"},
            "water_temperature": {"fr": "Température Eau (°C)", "en": "Water Temperature (°C)"},
            "swell_height": {"fr": "Hauteur Houle", "en": "Swell Height"},
            "swell_direction": {"fr": "Direction Houle", "en": "Swell Direction"}
        }

        for key, value in self.web_data.items():
            row_widget = QtWidgets.QWidget()
            h_layout = QtWidgets.QHBoxLayout(row_widget)
            h_layout.setContentsMargins(5, 2, 5, 2)
            h_layout.setSpacing(10)

            field_name = translation_labels.get(key, {}).get(self.lang, key)
            field_label = QtWidgets.QLabel(field_name)
            field_label.setStyleSheet("min-width: 170px; border: none;")
            h_layout.addWidget(field_label, 1)

            line_edit = QtWidgets.QLineEdit()
            line_edit.setText(str(value) if value is not None else "")
            line_edit.setReadOnly(True)
            h_layout.addWidget(line_edit, 2)

            form_layout.addWidget(row_widget)

        form_layout.addStretch()
        main_layout.addWidget(form_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QtWidgets.QPushButton("Fermer" if self.lang == "fr" else "Close")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)
