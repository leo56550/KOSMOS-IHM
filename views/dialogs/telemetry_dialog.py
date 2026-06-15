import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

_MISSING_STYLE = (
    "color: #5a7a8a; font-size: 11px; font-style: italic;"
    " font-family: 'Segoe UI', sans-serif;"
)

# Temp et pression : pas de curseur dynamique
_STATIC_METRICS = {"température", "pression"}

# Hauteur compacte quand les données statiques sont manquantes
_COMPACT_H = 36
# Hauteur normale pour un graphe avec données
_GRAPH_H   = 180


class TelemetryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analyse Télémétrie")
        self.resize(900, 800)

        pg.setConfigOptions(antialias=False, useOpenGL=True)

        self.full_df = None
        self.plots   = {}   # key → PlotDataItem
        self.stacks  = {}   # key → QStackedWidget
        self.v_lines = []   # InfiniteLines des métriques dynamiques seulement

        self.metrics = {
            "température": ("Température (°C)",  "#ff4d4d"),
            "pression":    ("Pression (hPa)",     "#4dff88"),
            "ExpTime":     ("Exposure Time (ms)", "#4da6ff"),
            "Lux":         ("Luminosité (Lux)",   "#ffff4d"),
        }

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(6, 6, 6, 6)

        for key, (label, color) in self.metrics.items():
            is_static = key in _STATIC_METRICS

            # ── Stack : page 0 = graph  |  page 1 = compact "manquant" ──
            stack = QtWidgets.QStackedWidget()

            # --- Graphe ---
            pw = pg.PlotWidget(title=label)
            pw.setBackground('#111820')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setMouseEnabled(x=True, y=True)
            curve = pw.plot(pen=pg.mkPen(color, width=1.5))

            if is_static:
                # Curseur gris positionné une seule fois, jamais redéplacé
                pw.addItem(pg.InfiniteLine(
                    pos=0, angle=90,
                    pen=pg.mkPen('#555555', width=1,
                                 style=QtCore.Qt.PenStyle.DashLine)
                ))
            else:
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
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()

            stack.addWidget(pw)        # index 0
            stack.addWidget(missing_w) # index 1

            # Stretch : dynamiques prennent plus de place que statiques
            stretch = 1 if is_static else 3
            self.plots[key]  = curve
            self.stacks[key] = stack
            main_layout.addWidget(stack, stretch=stretch)

    # ── Chargement des données (une seule fois) ───────────────────────────

    def update_data(self, df):
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

            y_data = self.full_df[key].values
            if (y_data != 0).sum() == 0:
                self._show_missing(key, stack)
            else:
                curve.setData(x_data, y_data)
                self._show_graph(key, stack)

        for v_line in self.v_lines:
            v_line.setValue(0)

    def _show_missing(self, key: str, stack: QtWidgets.QStackedWidget):
        stack.setCurrentIndex(1)
        if key in _STATIC_METRICS:
            stack.setMaximumHeight(_COMPACT_H)
        # Pour les métriques dynamiques, garder la hauteur normale même si vide
        else:
            stack.setMaximumHeight(16777215)

    def _show_graph(self, key: str, stack: QtWidgets.QStackedWidget):
        stack.setCurrentIndex(0)
        stack.setMaximumHeight(16777215)

    # ── Curseur dynamique (ExpTime + Lux seulement) ───────────────────────

    def update_cursor(self, current_seconds):
        for v_line in self.v_lines:
            v_line.setValue(current_seconds)
