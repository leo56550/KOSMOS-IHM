"""
Widget de vue globale campagne : toutes les vidéos sur un axe temps commun.

Chaque ligne = une vidéo.  Couleur = exploitabilité.  Losanges = événements.
Zoom à la molette ; clic = signal video_selected(row_index).
"""

from PyQt6 import QtCore, QtGui, QtWidgets


# ── Couleurs ───────────────────────────────────────────────────────────────────
_C_BG        = QtGui.QColor('#0d1b2a')
_C_ROW_EVEN  = QtGui.QColor('#0f1e2d')
_C_ROW_ODD   = QtGui.QColor('#0d1b2a')
_C_HOVER     = QtGui.QColor('#1a2e44')
_C_RULER_BG  = QtGui.QColor('#0a1520')
_C_LABEL_BG  = QtGui.QColor('#111f2e')
_C_LABEL_ALT = QtGui.QColor('#0d1a28')
_C_BORDER    = QtGui.QColor('#1e3448')
_C_ACCENT    = QtGui.QColor('#2778A2')
_C_TEXT      = QtGui.QColor('#d4e8f5')
_C_TICK      = QtGui.QColor('#7ec8e3')

_EXPLOIT_COLORS = {
    # français
    'oui':           ('#1a4a2e', '#4CAF50'),
    'non':           ('#4a1a1a', '#D94F38'),
    'habitat':       ('#1a2a4a', '#2778A2'),
    'communication': ('#2a1a4a', '#9B59B6'),
    '?':             ('#4a4a10', '#F1C40F'),
    # anglais
    'yes':           ('#1a4a2e', '#4CAF50'),
    'no':            ('#4a1a1a', '#D94F38'),
}
_C_UNVALIDATED = ('#141e2a', '#1e3448')

_EVENT_COLORS = {
    'events_animal':             '#f0c040',
    'events_interesting_images': '#D94F38',
    'events_deployment':         '#a0c4d8',
    'events_custom':             '#b0b0b0',
}
_C_EVENT_DEFAULT = '#8090a0'

# Nice tick intervals in ms (same pattern as VideoTimeline)
_NICE_TICKS = [
    500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
    60_000, 120_000, 300_000, 600_000, 1_800_000, 3_600_000, 7_200_000,
]


class CampaignOverviewWidget(QtWidgets.QWidget):
    """Visualisation multi-vidéos sur axe temps commun."""

    video_selected = QtCore.pyqtSignal(int)  # index dans entries

    RULER_H  = 28
    ROW_H    = 44
    LABEL_W  = 155
    BASE_PPS = 8   # pixels par seconde à zoom = 1

    def __init__(self, entries: list, parent=None):
        super().__init__(parent)
        self._entries   = entries
        self._zoom      = 1.0
        self._hover_row = -1
        self._total_ms  = sum(e.get('duration_ms', 0) for e in entries)
        self._fit_zoom()
        self.setMouseTracking(True)
        self._update_size()

    # ── API publique ───────────────────────────────────────────────────────────

    def update_entries(self, entries: list):
        """Remplace les données et redessine sans changer le zoom."""
        self._entries  = entries
        self._total_ms = sum(e.get('duration_ms', 0) for e in entries)
        self._update_size()
        self.update()

    def set_zoom(self, zoom: float):
        self._zoom = max(0.005, min(100.0, zoom))
        self._update_size()
        self.update()

    def fit_zoom(self, viewport_width: int, min_height: int = 0):
        """Ajuste le zoom pour que tout le contenu tienne dans viewport_width."""
        if self._total_ms > 0 and viewport_width > self.LABEL_W:
            needed = self._total_ms * self.BASE_PPS / 1000
            self._zoom = max(0.005, (viewport_width - self.LABEL_W) / needed)
        self._update_size(min_height)
        self.update()

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _fit_zoom(self):
        self.fit_zoom(950)

    def _ms_to_px(self, ms: int) -> int:
        return int(ms * self._zoom * self.BASE_PPS / 1000)

    def _update_size(self, min_height: int = 0):
        w = self.LABEL_W + self._ms_to_px(self._total_ms) + 2
        h = max(self.RULER_H + max(1, len(self._entries)) * self.ROW_H + 8, min_height)
        self.setMinimumSize(w, h)
        self.resize(w, h)

    def _tick_interval_ms(self) -> int:
        for t in _NICE_TICKS:
            if self._ms_to_px(t) >= 55:
                return t
        return _NICE_TICKS[-1]

    # ── Événements Qt ─────────────────────────────────────────────────────────

    def wheelEvent(self, event: QtGui.QWheelEvent):
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.set_zoom(self._zoom * factor)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        y = int(event.position().y())
        row = int((y - self.RULER_H) / self.ROW_H) if y > self.RULER_H else -1
        new_hover = row if 0 <= row < len(self._entries) else -1
        if new_hover != self._hover_row:
            self._hover_row = new_hover
            self.update()

    def leaveEvent(self, _):
        if self._hover_row != -1:
            self._hover_row = -1
            self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            y = int(event.position().y())
            row = int((y - self.RULER_H) / self.ROW_H) if y > self.RULER_H else -1
            if 0 <= row < len(self._entries):
                self.video_selected.emit(row)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        painter.fillRect(0, 0, W, H, _C_BG)

        self._draw_ruler(painter, W)

        offset_ms = 0
        for i, entry in enumerate(self._entries):
            y = self.RULER_H + i * self.ROW_H
            self._draw_row(painter, i, entry, y, offset_ms, W)
            offset_ms += entry.get('duration_ms', 0)

        # Séparateur colonne labels
        painter.setPen(QtGui.QPen(_C_ACCENT, 1))
        painter.drawLine(self.LABEL_W, 0, self.LABEL_W, H)

        painter.end()

    def _draw_ruler(self, painter: QtGui.QPainter, W: int):
        RH = self.RULER_H
        painter.fillRect(0,            0, W,           RH, _C_RULER_BG)
        painter.fillRect(0,            0, self.LABEL_W, RH, _C_BG)

        tick_ms  = self._tick_interval_ms()
        font = QtGui.QFont('Segoe UI', 7)
        painter.setFont(font)

        ms = 0
        while ms <= self._total_ms + tick_ms:
            x = self.LABEL_W + self._ms_to_px(ms)
            if x >= W:
                break

            painter.setPen(QtGui.QPen(_C_ACCENT, 1))
            painter.drawLine(x, RH - 9, x, RH)

            # Label temps
            s = ms // 1000
            h, rem = divmod(s, 3600)
            m, sc  = divmod(rem, 60)
            if h > 0:
                label = f"{h}h{m:02d}"
            elif m > 0:
                label = f"{m:02d}:{sc:02d}"
            else:
                label = f"{sc}s"

            painter.setPen(_C_TICK)
            painter.drawText(x + 3, 2, 80, RH - 4,
                             QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                             label)
            ms += tick_ms

        # Bordure basse de la règle
        painter.setPen(QtGui.QPen(_C_ACCENT, 1))
        painter.drawLine(0, RH - 1, W, RH - 1)

    def _draw_row(self, painter: QtGui.QPainter, idx: int, entry: dict,
                  y: int, offset_ms: int, W: int):
        RH, LW = self.ROW_H, self.LABEL_W

        # Fond ligne
        if idx == self._hover_row:
            row_bg = _C_HOVER
        elif idx % 2 == 0:
            row_bg = _C_ROW_EVEN
        else:
            row_bg = _C_ROW_ODD
        painter.fillRect(LW, y, W - LW, RH, row_bg)

        # Fond label
        lbl_bg = _C_LABEL_BG if idx % 2 == 0 else _C_LABEL_ALT
        painter.fillRect(0, y, LW, RH, lbl_bg)

        # Bloc vidéo (rectangle coloré selon exploitabilité)
        dur_ms = entry.get('duration_ms', 0)
        x0     = LW + self._ms_to_px(offset_ms)
        bw     = max(20, self._ms_to_px(dur_ms)) if dur_ms > 0 else 20
        exploit = (entry.get('exploitable') or '').lower().strip()
        fill_h, border_h = _EXPLOIT_COLORS.get(exploit, _C_UNVALIDATED)

        grad = QtGui.QLinearGradient(x0, y + 5, x0, y + RH - 5)
        base = QtGui.QColor(fill_h)
        grad.setColorAt(0.0, base.lighter(140))
        grad.setColorAt(1.0, base)
        painter.setBrush(QtGui.QBrush(grad))
        painter.setPen(QtGui.QPen(QtGui.QColor(border_h), 1))
        painter.drawRoundedRect(x0, y + 5, bw, RH - 10, 3, 3)

        # Événements
        painter.setBrush(QtGui.QBrush())   # reset brush for diamonds
        for ev in entry.get('events', []):
            ev_ms  = ev.get('time_ms', 0)
            ev_key = ev.get('type', 'events_custom')
            c_str  = _EVENT_COLORS.get(ev_key, _C_EVENT_DEFAULT)
            c      = QtGui.QColor(c_str)
            ex     = LW + self._ms_to_px(offset_ms + ev_ms)

            painter.setPen(QtGui.QPen(c, 1.5))
            painter.drawLine(ex, y + 7, ex, y + RH - 7)

            mid_y = y + RH // 2
            diamond = QtGui.QPolygonF([
                QtCore.QPointF(ex,     y + 6),
                QtCore.QPointF(ex + 4, mid_y),
                QtCore.QPointF(ex,     y + RH - 6),
                QtCore.QPointF(ex - 4, mid_y),
            ])
            painter.setBrush(QtGui.QBrush(c))
            painter.drawPolygon(diamond)
            painter.setBrush(QtGui.QBrush())

        # Nom de la vidéo (colonne label)
        font = QtGui.QFont('Segoe UI', 8)
        painter.setFont(font)
        painter.setPen(QtGui.QColor('#c8dce8') if idx != self._hover_row else _C_TEXT)
        fm    = painter.fontMetrics()
        name  = entry.get('name', '?')
        elided = fm.elidedText(name, QtCore.Qt.TextElideMode.ElideRight, LW - 14)
        painter.drawText(8, y, LW - 10, RH,
                         QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                         elided)

        # Séparateur ligne
        painter.setPen(QtGui.QPen(_C_BORDER, 1))
        painter.drawLine(0, y + RH - 1, W, y + RH - 1)
