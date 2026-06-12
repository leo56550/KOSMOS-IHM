import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets


class TelemetryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analyse Télémétrie")
        self.resize(900, 800)

        pg.setConfigOptions(antialias=False, useOpenGL=True)

        layout = QtWidgets.QVBoxLayout(self)

        self.full_df = None
        self.plots = {}
        self.v_lines = []

        self.metrics = {
            "température": ["Température (°C)", "#ff4d4d"],
            "pression": ["Pression (hPa)", "#4dff88"],
            "ExpTime": ["Exposure Time (ms)", "#4da6ff"],
            "Lux": ["Luminosité (Lux)", "#ffff4d"]
        }

        for key, info in self.metrics.items():
            pw = pg.PlotWidget(title=info[0])
            pw.setBackground('#1a1a1a')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setMouseEnabled(x=True, y=True)

            curve = pw.plot(pen=pg.mkPen(info[1], width=1.5))

            v_line = pg.InfiniteLine(
                pos=0,
                angle=90,
                pen=pg.mkPen('w', width=1, style=QtCore.Qt.PenStyle.DashLine),
                label='{value:0.2f}s',
                labelOpts={'position': 0.1, 'color': 'w', 'fill': (0, 0, 0, 150)}
            )
            pw.addItem(v_line)

            layout.addWidget(pw)
            self.plots[key] = curve
            self.v_lines.append(v_line)

    def update_data(self, df):
        """Appelé une seule fois au chargement du CSV."""
        if df is None or df.empty:
            return

        self.full_df = df
        x_data = self.full_df['Delta'].values

        for key, curve in self.plots.items():
            if key in self.full_df.columns:
                curve.setData(x_data, self.full_df[key].values)
            else:
                curve.setData([], [])

        for v_line in self.v_lines:
            v_line.setValue(0)

    def update_cursor(self, current_seconds):
        """Mise à jour légère : déplace seulement le curseur vertical."""
        for v_line in self.v_lines:
            v_line.setValue(current_seconds)
