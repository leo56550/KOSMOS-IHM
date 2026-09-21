import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

_MISSING_STYLE = (
    "color: #5a7a8a; font-size: 11px; font-style: italic;"
    " font-family: 'Segoe UI', sans-serif;"
)

# Hauteur compacte quand les données sont manquantes
_COMPACT_H = 36


class _TimeAxis(pg.AxisItem):
    """Axe X pyqtgraph qui affiche les secondes au format MM:SS."""
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            try:
                total_s = int(round(float(v)))
                sign = "-" if total_s < 0 else ""
                total_s = abs(total_s)
                m, s = divmod(total_s, 60)
                out.append(f"{sign}{m:02d}:{s:02d}")
            except (TypeError, ValueError):
                out.append("")
        return out


_LUX_RGB_COLS = {
    'RLux': ('#ff4040', 'R'),
    'GLux': ('#40dd70', 'G'),
    'BLux': ('#4090ff', 'B'),
}


class TelemetryDialog(QtWidgets.QDialog):
    """Dialogue d'analyse télémétrie : graphes pyqtgraph (température, profondeur, exposition, RGB lux)."""

    time_clicked = QtCore.pyqtSignal(float)  # secondes depuis le début de la vidéo

    _METRIC_TRANSLATIONS = {
        "température":  ("Température (°C)",       "Temperature (°C)"),
        "profondeur":   ("Profondeur (m)",          "Depth (m)"),
        "ExpTime":      ("Temps d'exposition (ms)", "Exposure Time (ms)"),
        "lux_rgb":      ("Luminosité RGB (Lux)",   "RGB Luminosity (Lux)"),
    }

    def __init__(self, parent=None):
        """Initialise les graphes pyqtgraph et les curseurs dynamiques pour chaque métrique."""
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.current_language = 'fr'
        self.setWindowTitle("Analyse Télémétrie")
        self.resize(900, 800)

        pg.setConfigOptions(antialias=False, useOpenGL=True)

        self.full_df = None
        self.plots        = {}   # key → PlotDataItem
        self.stacks       = {}   # key → QStackedWidget
        self.plot_widgets = {}   # key → PlotWidget (for title updates)
        self.missing_labels = {} # key → QLabel (for "données manquantes" text updates)
        self._lux_rgb_curves = {}  # col → PlotDataItem (RLux, GLux, BLux)

        self.metrics = {
            "température":  ("Température (°C)",       "#ff4d4d"),
            "profondeur":   ("Profondeur (m)",          "#4dff88"),
            "ExpTime":      ("Temps d'exposition (ms)", "#4da6ff"),
        }

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(6, 6, 6, 6)

        for key, (label, color) in self.metrics.items():
            # ── Stack : page 0 = graph  |  page 1 = compact "manquant" ──
            stack = QtWidgets.QStackedWidget()

            # --- Graphe ---
            pw = pg.PlotWidget(title=label, axisItems={'bottom': _TimeAxis(orientation='bottom')})
            self.plot_widgets[key] = pw
            pw.setBackground('#111820')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setMouseEnabled(x=True, y=True)
            if key == "profondeur":
                pw.invertY(True)
            curve = pw.plot(pen=pg.mkPen(color, width=1.5))
            pw.scene().sigMouseClicked.connect(
                lambda evt, _pw=pw: self._on_graph_clicked(evt, _pw))

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

        # ── Graphe RGB Lux (3 courbes sur un même PlotWidget) ────────────────
        _lux_label = "Luminosité RGB (Lux)"
        pw_lux = pg.PlotWidget(title=_lux_label, axisItems={'bottom': _TimeAxis(orientation='bottom')})
        self.plot_widgets["lux_rgb"] = pw_lux
        pw_lux.setBackground('#111820')
        pw_lux.showGrid(x=True, y=True, alpha=0.3)
        pw_lux.setMouseEnabled(x=True, y=True)

        legend = pw_lux.addLegend(offset=(10, 10))
        legend.setLabelTextColor('w')

        for col, (color, name) in _LUX_RGB_COLS.items():
            self._lux_rgb_curves[col] = pw_lux.plot(
                pen=pg.mkPen(color, width=1.5), name=name
            )

        pw_lux.scene().sigMouseClicked.connect(
            lambda evt, _pw=pw_lux: self._on_graph_clicked(evt, _pw))

        stack_lux = QtWidgets.QStackedWidget()
        missing_lux = QtWidgets.QWidget()
        missing_lux.setStyleSheet("background-color: #111820;")
        missing_lux.setFixedHeight(_COMPACT_H)
        row_lux = QtWidgets.QHBoxLayout(missing_lux)
        row_lux.setContentsMargins(12, 4, 12, 4)
        dot_lux = QtWidgets.QLabel("● ● ●")
        dot_lux.setStyleSheet("color: #a060a0; font-size: 10px; border: none;")
        lbl_lux = QtWidgets.QLabel(f"{_lux_label} — données manquantes")
        lbl_lux.setStyleSheet(_MISSING_STYLE)
        self.missing_labels["lux_rgb"] = lbl_lux
        row_lux.addWidget(dot_lux)
        row_lux.addWidget(lbl_lux)
        row_lux.addStretch()

        stack_lux.addWidget(pw_lux)
        stack_lux.addWidget(missing_lux)
        self.stacks["lux_rgb"] = stack_lux
        main_layout.addWidget(stack_lux, stretch=3)

        # ── Bouton Réinitialiser ─────────────────────────────────────────────
        self._btn_reset = QtWidgets.QPushButton("RÉINITIALISER")
        self._btn_reset.setFixedHeight(28)
        self._btn_reset.setStyleSheet(
            "QPushButton { background: #1a3a50; color: #7ec8e3; border: 1px solid #2778A2;"
            " border-radius: 4px; font-size: 11px; font-family: 'Segoe UI'; padding: 0 12px; }"
            "QPushButton:hover { background: #2778A2; color: #ffffff; }"
            "QPushButton:pressed { background: #1a5070; }"
        )
        self._btn_reset.clicked.connect(self._reset_all_views)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._btn_reset)
        main_layout.addLayout(btn_row)

    # ── Language ──────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        """Retourne la chaîne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def _reset_all_views(self):
        """Remet tous les graphes visibles en vue auto (zoom/pan réinitialisé)."""
        for pw in self.plot_widgets.values():
            pw.enableAutoRange()
            pw.autoRange()

    def set_language(self, language: str):
        """Met à jour la langue, le titre et les libellés des métriques."""
        self.current_language = language
        self.setWindowTitle(self.translate("Analyse Télémétrie", "Telemetry Analysis"))
        self._btn_reset.setText(self.translate("RÉINITIALISER", "RESET VIEW"))
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

        # Métriques simples (une courbe par graphe)
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

        # Graphe RGB Lux (3 courbes sur un même axe)
        any_lux = False
        for col, curve in self._lux_rgb_curves.items():
            if col not in self.full_df.columns:
                curve.setData([], [])
                continue
            try:
                y = self.full_df[col].values.astype(float)
            except (ValueError, TypeError):
                curve.setData([], [])
                continue
            valid = y[~np.isnan(y)]
            if len(valid) > 0 and (valid != 0).sum() > 0:
                curve.setData(x_data, y)
                any_lux = True
            else:
                curve.setData([], [])

        if any_lux:
            self._show_graph("lux_rgb", self.stacks["lux_rgb"])
        else:
            self._show_missing("lux_rgb", self.stacks["lux_rgb"])

    def _show_missing(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page 'données manquantes' (bandeau compact)."""
        stack.setCurrentIndex(1)
        stack.setMaximumHeight(_COMPACT_H)

    def _show_graph(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page graphe et restaure la hauteur maximale."""
        stack.setCurrentIndex(0)
        stack.setMaximumHeight(16777215)

    def _on_graph_clicked(self, event, pw):
        """Émet time_clicked (en secondes) quand l'utilisateur clique sur un graphe."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = pw.getViewBox()
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(event.scenePos())
        t = mouse_point.x()
        if self.full_df is not None and 'Delta' in self.full_df.columns:
            t_max = float(self.full_df['Delta'].max())
            t = max(0.0, min(t, t_max))
        else:
            t = max(0.0, t)
        self.time_clicked.emit(t)

