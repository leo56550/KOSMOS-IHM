import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

_MISSING_STYLE = (
    "color: #5a7a8a; font-size: 11px; font-style: italic;"
    " font-family: 'Segoe UI', sans-serif;"
)

# Hauteur compacte quand les données sont manquantes
_COMPACT_H = 36


class TelemetryDialog(QtWidgets.QDialog):
    """Dialogue d'analyse télémétrie : graphes pyqtgraph (température, pression, exposition, luminosité)."""

    _METRIC_TRANSLATIONS = {
        "température": ("Température (°C)",       "Temperature (°C)"),
        "pression":    ("Pression (hPa)",          "Pressure (hPa)"),
        "ExpTime":     ("Temps d'exposition (ms)", "Exposure Time (ms)"),
        "Lux":         ("Luminosité (Lux)",        "Luminosity (Lux)"),
    }

    def __init__(self, parent=None):
        """Initialise les graphes pyqtgraph et les curseurs dynamiques pour chaque métrique."""
        super().__init__(parent)
        self.current_language = 'fr'
        self.setWindowTitle("Analyse Télémétrie")
        self.resize(900, 800)

        pg.setConfigOptions(antialias=False, useOpenGL=True)

        self.full_df = None
        self.plots        = {}   # key → PlotDataItem
        self.stacks       = {}   # key → QStackedWidget
        self.v_lines      = []   # InfiniteLines des métriques dynamiques seulement
        self.plot_widgets = {}   # key → PlotWidget (for title updates)
        self.missing_labels = {} # key → QLabel (for "données manquantes" text updates)

        self.metrics = {
            "température": ("Température (°C)",       "#ff4d4d"),
            "pression":    ("Pression (hPa)",          "#4dff88"),
            "ExpTime":     ("Temps d'exposition (ms)", "#4da6ff"),
            "Lux":         ("Luminosité (Lux)",        "#ffff4d"),
        }

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(6, 6, 6, 6)

        for key, (label, color) in self.metrics.items():
            # ── Stack : page 0 = graph  |  page 1 = compact "manquant" ──
            stack = QtWidgets.QStackedWidget()

            # --- Graphe ---
            pw = pg.PlotWidget(title=label)
            self.plot_widgets[key] = pw
            pw.setBackground('#111820')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setMouseEnabled(x=True, y=True)
            curve = pw.plot(pen=pg.mkPen(color, width=1.5))

            v_line = pg.InfiniteLine(
                pos=0, angle=90,
                pen=pg.mkPen('w', width=1,
                             style=QtCore.Qt.PenStyle.DashLine),
                label='{value:0.2f}s',
                labelOpts={'position': 0.1, 'color': 'w',
                           'fill': (0, 0, 0, 150)}
            )
            pw.addItem(v_line)
            self.v_lines.append(v_line)

            # --- Bandeau "données manquantes" (très compact) ---
            missing_w = QtWidgets.QWidget()
            missing_w.setStyleSheet("background-color: #111820;")
            missing_w.setFixedHeight(_COMPACT_H)
            row = QtWidgets.QHBoxLayout(missing_w)
            row.setContentsMargins(12, 4, 12, 4)
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px; border: none;")
            lbl = QtWidgets.QLabel(f"{label} — données manquantes")
            lbl.setStyleSheet(_MISSING_STYLE)
            self.missing_labels[key] = lbl
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()

            stack.addWidget(pw)        # index 0
            stack.addWidget(missing_w) # index 1

            self.plots[key]  = curve
            self.stacks[key] = stack
            main_layout.addWidget(stack, stretch=3)

    # ── Language ──────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        """Retourne la chaîne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Met à jour la langue, le titre et les libellés des métriques."""
        self.current_language = language
        self.setWindowTitle(self.translate("Analyse Télémétrie", "Telemetry Analysis"))
        missing_suffix = self.translate("données manquantes", "missing data")
        for key, (fr_label, en_label) in self._METRIC_TRANSLATIONS.items():
            label = fr_label if language == 'fr' else en_label
            if key in self.plot_widgets:
                self.plot_widgets[key].setTitle(label)
            if key in self.missing_labels:
                self.missing_labels[key].setText(f"{label} — {missing_suffix}")

    # ── Chargement des données (une seule fois) ───────────────────────────

    def update_data(self, df):
        """Charge le DataFrame de télémétrie et trace les courbes (ou affiche 'manquant')."""
        if df is None or df.empty:
            for key, stack in self.stacks.items():
                self._show_missing(key, stack)
            return

        self.full_df = df
        x_data = self.full_df['Delta'].values

        for key, curve in self.plots.items():
            stack = self.stacks[key]
            if key not in self.full_df.columns:
                self._show_missing(key, stack)
                continue

            try:
                y_data = self.full_df[key].values.astype(float)
            except (ValueError, TypeError):
                self._show_missing(key, stack)
                continue

            valid = y_data[~np.isnan(y_data)]
            if len(valid) == 0 or (valid != 0).sum() == 0:
                self._show_missing(key, stack)
            else:
                curve.setData(x_data, y_data)
                self._show_graph(key, stack)

        for v_line in self.v_lines:
            v_line.setValue(0)

    def _show_missing(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page 'données manquantes' (bandeau compact)."""
        stack.setCurrentIndex(1)
        stack.setMaximumHeight(_COMPACT_H)

    def _show_graph(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page graphe et restaure la hauteur maximale."""
        stack.setCurrentIndex(0)
        stack.setMaximumHeight(16777215)

    # ── Curseur dynamique (ExpTime + Lux seulement) ───────────────────────

    def update_cursor(self, current_seconds):
        """Déplace les curseurs verticaux dynamiques à la position temporelle courante."""
        for v_line in self.v_lines:
            v_line.setValue(current_seconds)
