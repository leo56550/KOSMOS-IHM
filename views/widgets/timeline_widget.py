from PyQt6 import QtCore, QtGui, QtWidgets


class VideoTimeline(QtWidgets.QWidget):
    """
    Custom Timeline widget featuring horizontal Zoom support
    AND interactive editing (stretching/shrinking AND horizontal dragging).
    """
    sliderMoved = QtCore.pyqtSignal(int)
    timeChanged = QtCore.pyqtSignal(int)
    eventResized = QtCore.pyqtSignal(dict)
    eventMoved = QtCore.pyqtSignal(dict)
    eventSelected = QtCore.pyqtSignal(object)  # dict or None
    zoomChanged = QtCore.pyqtSignal(float)
    markersChanged = QtCore.pyqtSignal(int, int)

    def __init__(self, events=None, parent=None, zone_definitions=None):
        """Initialise la timeline avec des événements et des définitions de zones optionnelles."""
        super().__init__(parent)
        self.events = events if events is not None else []
        self.zone_definitions = zone_definitions if zone_definitions is not None else []
        self.current_pos = 0
        self.total_duration = 0
        self.is_dragging = False
        self.zoom_factor = 1.0

        self.segments = []
        self.selected_event_dict = None

        self.start_marker_ms = 0
        self.end_marker_ms = 0

        self.resize_margin = 6
        self.active_resize_event = None
        self.resize_edge = None

        self.active_move_event = None
        self.drag_start_mouse_x = 0
        self.drag_start_event_start = 0
        self.drag_start_event_end = 0

        self.rects_evenements = {}

        self.setMinimumHeight(160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def _clamp_int(self, value):
        """Clamp value dans l'intervalle des entiers 32 bits signés, retourne 0 si invalide."""
        try:
            val = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        if val < -2147483648: return -2147483648
        if val > 2147483647: return 2147483647
        return val

    def set_zoom(self, factor):
        """Applique le facteur de zoom et déclenche un repaint."""
        self.zoom_factor = max(1.0, factor)
        # setMinimumWidth force la QScrollArea (même en setWidgetResizable(True)) à créer
        # une scrollbar réelle — sans ça le max scrollbar reste 0 et tout reste ancré à t=0.
        self.setMinimumWidth(self.min_zoomed_width())
        self.updateGeometry()
        self.update()

    def min_zoomed_width(self):
        """Retourne la largeur effective en pixels (largeur viewport × zoom_factor)."""
        p = self.parent()
        base_width = p.width() if p is not None else self.width()
        return int(base_width * self.zoom_factor)

    def sizeHint(self):
        """Indique à Qt la taille souhaitée pour que le QScrollArea horizontal soit correct."""
        return QtCore.QSize(self.min_zoomed_width(), self.height())

    def set_total_duration(self, duration_ms):
        """Fixe la durée totale et force un repaint."""
        self.total_duration = duration_ms
        self.updateGeometry()
        self.update()

    def set_current_position(self, position_ms):
        """Met à jour la position du curseur de lecture (ignoré si un drag/resize est en cours)."""
        if not self.is_dragging and not self.active_resize_event and not self.active_move_event:
            self.current_pos = position_ms
            self.update()

    def get_current_position(self) -> int:
        """Retourne la position courante du curseur en millisecondes."""
        return self.current_pos

    def set_selected_event(self, event_dict):
        """Sélectionne un événement (ou None) et rafraîchit l'affichage."""
        self.selected_event_dict = event_dict
        self.update()

    def calculate_segments(self):
        """Construit la liste des segments atterrissage→décollage à partir des événements."""
        self.segments = []
        takeoffs = []
        landings = []

        for evt in self.events:
            title = evt.get("title", "").lower()
            if "atterrissage" in title or "landing" in title:
                landings.append(evt)
            elif "décollage" in title or "takeoff" in title or "take_off" in title:
                takeoffs.append(evt)

        for landing in landings:
            start_time = landing.get("end", landing.get("start", 0))
            next_takeoff = None
            for takeoff in takeoffs:
                takeoff_time = takeoff.get("start", takeoff.get("end", 0))
                if takeoff_time > start_time:
                    if next_takeoff is None or takeoff_time < next_takeoff.get("start", next_takeoff.get("end", 0)):
                        next_takeoff = takeoff
            if next_takeoff:
                end_time = next_takeoff.get("start", next_takeoff.get("end", 0))
                self.segments.append({
                    "start": start_time,
                    "end": end_time,
                    "zone": landing.get("zone", 0)
                })

    # ── Constantes visuelles ──────────────────────────────────────────────────
    RULER_H        = 26
    C_BG           = "#0d1b2a"
    C_RULER_BG     = "#0a1520"
    C_RULER_BORDER = "#2778A2"
    C_RULER_TICK   = "#2a4a62"
    C_RULER_TEXT   = "#7ec8e3"
    C_GRID         = (39, 100, 140, 45)   # RGBA
    C_PLAYHEAD     = "#00d4ff"
    C_MOTOR        = "#f0c040"
    C_MOTOR360     = "#ff5555"
    C_MARKER_IN    = "#2ecc71"
    C_MARKER_OUT   = "#e74c3c"

    # Per-zone: (zone_bg, event_fill_top, event_fill_bot, event_border)
    ZONE_STYLES = [
        (QtGui.QColor(16, 36, 52, 200),  QtGui.QColor(36, 80, 120),  QtGui.QColor(20, 55, 90),  QtGui.QColor("#2778A2")),
        (QtGui.QColor(20, 44, 68, 200),  QtGui.QColor(30, 100, 155), QtGui.QColor(20, 70, 115), QtGui.QColor("#3498db")),
        (QtGui.QColor(48, 14, 18, 200),  QtGui.QColor(130, 40, 35),  QtGui.QColor(90, 25, 20),  QtGui.QColor("#D94F38")),
    ]

    def paintEvent(self, event):
        """Dessine la timeline : règle temporelle, zones, événements, playhead et marqueurs."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        self.calculate_segments()

        RH = self.RULER_H
        width = self.min_zoomed_width()
        H = self.height()
        total_duration = self.total_duration if self.total_duration > 0 else 1

        # ── Fond général ────────────────────────────────────────────────────
        painter.fillRect(0, RH, width, H - RH, QtGui.QColor(self.C_BG))

        # ── Zones ───────────────────────────────────────────────────────────
        track_height = 22
        zone_defs = self.zone_definitions or []
        zone_top_margin = RH + 2

        if not zone_defs:
            zone_count, zone_spacing = 1, 0
            zone_height = max(28, H - zone_top_margin - 2)
            zone_rows = {0: []}
        else:
            zone_count = len(zone_defs)
            zone_spacing = 3
            zone_height = max(38, (H - zone_top_margin - (zone_count - 1) * zone_spacing - 2) // zone_count)
            zone_rows = {i: [] for i in range(zone_count)}

        for zi in range(zone_count):
            y_z = zone_top_margin + zi * (zone_height + zone_spacing)
            style = self.ZONE_STYLES[zi] if zi < len(self.ZONE_STYLES) else self.ZONE_STYLES[-1]
            zone_bg = style[0]

            painter.fillRect(0, y_z, width, zone_height, zone_bg)

            # Barre colorée gauche + label
            if zone_defs and zi < len(zone_defs):
                bar_color = zone_defs[zi].get("color", QtGui.QColor("#2778A2"))
                painter.fillRect(0, y_z, 3, zone_height, bar_color)
                lbl = zone_defs[zi].get("label", "").upper()
                f_lbl = QtGui.QFont("Segoe UI", 7, QtGui.QFont.Weight.Bold)
                painter.setFont(f_lbl)
                painter.setPen(QtGui.QColor(255, 255, 255, 55))
                painter.drawText(7, y_z + 13, lbl)

            # Séparateur bas de zone
            painter.setPen(QtGui.QPen(QtGui.QColor("#162433"), 1))
            painter.drawLine(0, y_z + zone_height, width, y_z + zone_height)

        # ── Grille temporelle (vertical, fond) ───────────────────────────────
        tick_ms = self._get_tick_interval(width, total_duration)
        if tick_ms > 0:
            grid_pen = QtGui.QPen(QtGui.QColor(*self.C_GRID), 1)
            painter.setPen(grid_pen)
            t = tick_ms
            while t < total_duration:
                x = self._clamp_int((t / total_duration) * width)
                painter.drawLine(x, RH, x, H)
                t += tick_ms

        # ── Segments (atterrissage→décollage) ────────────────────────────────
        self.rects_evenements.clear()

        for seg in self.segments:
            xs = self._clamp_int((seg.get("start", 0) / total_duration) * width)
            xe = self._clamp_int((seg.get("end", 0) / total_duration) * width)
            zi = max(0, min(seg.get("zone", 0), zone_count - 1))
            y_z = zone_top_margin + zi * (zone_height + zone_spacing)
            painter.fillRect(xs, y_z, max(1, xe - xs), zone_height, QtGui.QColor(80, 180, 255, 22))
            painter.setPen(QtGui.QPen(QtGui.QColor(80, 180, 255, 60), 1))
            painter.drawRect(xs, y_z, max(1, xe - xs), zone_height)

        # ── Événements ──────────────────────────────────────────────────────
        for idx, evt in enumerate(self.events):
            start_ms = evt.get("start", 0)
            end_ms   = evt.get("end", 0)
            title    = evt.get("title", "")
            evt_type = evt.get("type", "")
            x_start  = self._clamp_int((start_ms / total_duration) * width)

            if evt_type != "custom_event":
                is_360 = "360" in str(evt_type).lower()
                c_line = QtGui.QColor(self.C_MOTOR360 if is_360 else self.C_MOTOR)
                dash_pen = QtGui.QPen(c_line, 1.5 if is_360 else 1)
                dash_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
                painter.setPen(dash_pen)
                painter.drawLine(x_start, RH, x_start, H)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(c_line)
                painter.drawEllipse(QtCore.QPoint(x_start, RH + 5), 3, 3)
                continue

            x_end      = self._clamp_int((end_ms / total_duration) * width)
            rect_width = self._clamp_int(max(x_end - x_start, 8))
            zi = max(0, min(evt.get("zone", 0), zone_count - 1))
            y_z = zone_top_margin + zi * (zone_height + zone_spacing)
            style = self.ZONE_STYLES[zi] if zi < len(self.ZONE_STYLES) else self.ZONE_STYLES[-1]

            # Placement multi-lignes anti-overlap
            row_index = 0
            while row_index < len(zone_rows[zi]):
                overlap = any(
                    not (x_end <= iv[0] or x_start >= iv[1])
                    for iv in zone_rows[zi][row_index]
                )
                if not overlap:
                    break
                row_index += 1
            if row_index >= len(zone_rows[zi]):
                zone_rows[zi].append([])
            zone_rows[zi][row_index].append((x_start, x_end))

            y_pos = y_z + 6 + row_index * (track_height + 3)
            if y_pos + track_height > y_z + zone_height - 3:
                y_pos = y_z + 6

            rect_box = QtCore.QRect(self._clamp_int(x_start), y_pos, rect_width, track_height)
            self.rects_evenements[idx] = (evt, rect_box)

            is_selected = (
                self.selected_event_dict is not None
                and evt.get("title") == self.selected_event_dict.get("title")
                and evt.get("start") == self.selected_event_dict.get("start")
            )

            _, fill_top, fill_bot, border_col = style

            # Gradient vertical
            grad = QtGui.QLinearGradient(
                QtCore.QPointF(rect_box.left(), rect_box.top()),
                QtCore.QPointF(rect_box.left(), rect_box.bottom())
            )
            grad.setColorAt(0.0, fill_top)
            grad.setColorAt(1.0, fill_bot)

            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect_box), 3, 3)
            painter.fillPath(path, grad)

            if is_selected:
                glow = QtGui.QPen(QtGui.QColor(self.C_PLAYHEAD), 1.5)
                painter.setPen(glow)
            else:
                painter.setPen(QtGui.QPen(border_col, 1))
            painter.drawPath(path)

            # Handles resize
            if rect_width > 12:
                hc = QtGui.QColor(255, 255, 255, 60)
                painter.setPen(hc)
                for hx in (x_start + 3, x_end - 3):
                    painter.drawLine(hx, y_pos + 4, hx, y_pos + track_height - 4)

            # Label
            f_evt = QtGui.QFont("Segoe UI", 8)
            painter.setFont(f_evt)
            txt_color = QtGui.QColor(220, 238, 255) if not is_selected else QtGui.QColor("#00d4ff")
            painter.setPen(txt_color)
            if rect_width > 70:
                ts = self._format_ms(start_ms)
                te = self._format_ms(end_ms)
                full = f"{ts}  {title}  {te}"
                shown = painter.fontMetrics().elidedText(full, QtCore.Qt.TextElideMode.ElideRight, rect_width - 10)
                painter.drawText(
                    QtCore.QRect(x_start + 5, y_pos, rect_width - 10, track_height),
                    QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft, shown
                )
            elif rect_width > 28:
                shown = painter.fontMetrics().elidedText(title, QtCore.Qt.TextElideMode.ElideRight, rect_width - 6)
                painter.drawText(
                    QtCore.QRect(x_start + 3, y_pos, rect_width - 6, track_height),
                    QtCore.Qt.AlignmentFlag.AlignCenter, shown
                )

        # ── Règle temporelle (dessinée en dernier pour être au-dessus) ───────
        self._draw_ruler(painter, width, RH, total_duration)

        # ── Playhead ────────────────────────────────────────────────────────
        x_cur = self._clamp_int((self.current_pos / total_duration) * width)

        # Ligne verticale
        painter.setPen(QtGui.QPen(QtGui.QColor(self.C_PLAYHEAD), 1.5))
        painter.drawLine(x_cur, RH, x_cur, H)

        # Triangle dans la règle
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(self.C_PLAYHEAD))
        tri = [
            QtCore.QPoint(x_cur,     RH + 1),
            QtCore.QPoint(x_cur - 5, RH - 7),
            QtCore.QPoint(x_cur + 5, RH - 7),
        ]
        painter.drawPolygon(tri)

        # Badge temps dans la règle
        time_str = self._format_ms(self.current_pos)
        f_badge = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Weight.Bold)
        painter.setFont(f_badge)
        fm = painter.fontMetrics()
        bw = fm.horizontalAdvance(time_str) + 10
        bh = 15
        bx = max(1, min(x_cur - bw // 2, width - bw - 1))
        by = (RH - bh) // 2 - 1
        badge_path = QtGui.QPainterPath()
        badge_path.addRoundedRect(QtCore.QRectF(bx, by, bw, bh), 3, 3)
        painter.fillPath(badge_path, QtGui.QColor(self.C_PLAYHEAD))
        painter.setPen(QtGui.QColor("#001c28"))
        painter.drawText(QtCore.QRect(bx, by, bw, bh), QtCore.Qt.AlignmentFlag.AlignCenter, time_str)

        # ── Marqueurs In / Out ───────────────────────────────────────────────
        if self.start_marker_ms > 0:
            xm = self._clamp_int((self.start_marker_ms / total_duration) * width)
            painter.setPen(QtGui.QPen(QtGui.QColor(self.C_MARKER_IN), 1.5))
            painter.drawLine(xm, RH, xm, H)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(self.C_MARKER_IN))
            painter.drawPolygon([
                QtCore.QPoint(xm,     RH),
                QtCore.QPoint(xm,     RH + 10),
                QtCore.QPoint(xm + 8, RH),
            ])

        if self.end_marker_ms > 0:
            xm = self._clamp_int((self.end_marker_ms / total_duration) * width)
            painter.setPen(QtGui.QPen(QtGui.QColor(self.C_MARKER_OUT), 1.5))
            painter.drawLine(xm, RH, xm, H)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(self.C_MARKER_OUT))
            painter.drawPolygon([
                QtCore.QPoint(xm,     RH),
                QtCore.QPoint(xm,     RH + 10),
                QtCore.QPoint(xm - 8, RH),
            ])

        painter.end()

    # ── Helpers visuels ───────────────────────────────────────────────────────

    def _get_tick_interval(self, width: int, total_duration: int) -> int:
        """Retourne l'intervalle entre ticks mineurs (ms) pour ~50px d'espacement."""
        if total_duration <= 0 or width <= 0:
            return 0
        ms_per_px = total_duration / width
        raw = 50 * ms_per_px
        for step in (200, 500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
                     60_000, 120_000, 300_000, 600_000, 1_800_000, 3_600_000):
            if step >= raw:
                return step
        return 3_600_000

    def _draw_ruler(self, painter: QtGui.QPainter, width: int, ruler_h: int, total_duration: int):
        """Dessine la règle temporelle avec ticks majeurs/mineurs et labels adaptatifs."""
        # Fond règle
        painter.fillRect(0, 0, width, ruler_h, QtGui.QColor(self.C_RULER_BG))
        # Bordure bas
        painter.setPen(QtGui.QPen(QtGui.QColor(self.C_RULER_BORDER), 1))
        painter.drawLine(0, ruler_h - 1, width, ruler_h - 1)

        if total_duration <= 0:
            return

        tick_ms = self._get_tick_interval(width, total_duration)
        if tick_ms <= 0:
            return

        px_per_tick = (tick_ms / total_duration) * width
        # Affiche un label tous les N ticks pour que les labels soient espacés d'~80px
        label_every = max(1, int(80 / max(px_per_tick, 1)))

        f_tick = QtGui.QFont("Segoe UI", 7)
        painter.setFont(f_tick)
        fm = painter.fontMetrics()

        t, n = 0, 0
        while t <= total_duration:
            x = self._clamp_int((t / total_duration) * width)
            is_major = (n % label_every == 0)

            if is_major:
                painter.setPen(QtGui.QPen(QtGui.QColor(self.C_RULER_BORDER), 1))
                painter.drawLine(x, ruler_h - 12, x, ruler_h - 1)
                label = self._format_ms(t)
                lw = fm.horizontalAdvance(label)
                lx = max(2, min(x - lw // 2, width - lw - 2))
                painter.setPen(QtGui.QColor(self.C_RULER_TEXT))
                painter.drawText(lx, ruler_h - 14, label)
            else:
                painter.setPen(QtGui.QPen(QtGui.QColor(self.C_RULER_TICK), 1))
                painter.drawLine(x, ruler_h - 5, x, ruler_h - 1)

            t += tick_ms
            n += 1

    def mousePressEvent(self, event):
        """Démarre un drag timeline, un redimensionnement ou un déplacement d'événement selon la position."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self.total_duration <= 0:
            return

        pos_x = event.position().x()
        pos_y = event.position().y()
        width = self.min_zoomed_width()
        total_duration = self.total_duration if self.total_duration > 0 else 1
        click_ms = (pos_x / width) * total_duration
        margin_ms = (10 / width) * total_duration

        if abs(click_ms - self.start_marker_ms) < margin_ms:
            self.active_resize_marker = "start"
            return
        elif abs(click_ms - self.end_marker_ms) < margin_ms:
            self.active_resize_marker = "end"
            return

        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(int(pos_x), int(pos_y)):
                self.set_selected_event(evt)
                self.eventSelected.emit(evt)

                if evt.get("zone", -1) == 2 or evt.get("single_frame", False) or evt.get("start") == evt.get("end"):
                    self.active_move_event = evt
                    self.drag_start_mouse_x = pos_x
                    self.drag_start_event_start = evt["start"]
                    self.drag_start_event_end = evt["end"]
                    return

                if abs(pos_x - rect.left()) <= self.resize_margin:
                    self.active_resize_event = evt
                    self.resize_edge = "left"
                    return
                elif abs(pos_x - rect.right()) <= self.resize_margin:
                    self.active_resize_event = evt
                    self.resize_edge = "right"
                    return
                else:
                    self.active_move_event = evt
                    self.drag_start_mouse_x = pos_x
                    self.drag_start_event_start = evt["start"]
                    self.drag_start_event_end = evt["end"]
                    return

        self.set_selected_event(None)
        self.eventSelected.emit(None)
        self.is_dragging = True
        self.calculate_and_emit_position(pos_x)

    def mouseMoveEvent(self, event):
        """Gère le redimensionnement, déplacement d'événement, drag curseur et curseur souris."""
        pos_x = event.position().x()
        width = self.min_zoomed_width()
        total_duration = self.total_duration if self.total_duration > 0 else 1
        current_ms = int((max(0.0, min(pos_x / width, 1.0))) * total_duration)

        if hasattr(self, 'active_resize_marker'):
            if self.active_resize_marker == "start":
                self.start_marker_ms = max(0, min(current_ms, self.end_marker_ms - 100))
            else:
                self.end_marker_ms = min(total_duration, max(current_ms, self.start_marker_ms + 100))
            self.markersChanged.emit(self.start_marker_ms, self.end_marker_ms)
            self.update()
            return

        if self.active_resize_event:
            if self.resize_edge == "left" and current_ms < self.active_resize_event["end"]:
                self.active_resize_event["start"] = current_ms
            elif self.resize_edge == "right" and current_ms > self.active_resize_event["start"]:
                self.active_resize_event["end"] = current_ms
            self.update()
            return

        if self.active_move_event:
            delta_pixels = pos_x - self.drag_start_mouse_x
            delta_ms = int((delta_pixels / width) * total_duration)
            new_start = self.drag_start_event_start + delta_ms
            new_end = self.drag_start_event_end + delta_ms
            block_dur = self.drag_start_event_end - self.drag_start_event_start
            if new_start < 0:
                new_start, new_end = 0, block_dur
            elif new_end > self.total_duration:
                new_end = self.total_duration
                new_start = self.total_duration - block_dur
            self.active_move_event["start"], self.active_move_event["end"] = new_start, new_end
            self.update()
            return

        if self.is_dragging:
            self.calculate_and_emit_position(pos_x)
            return

        margin_ms = (10 / width) * total_duration
        if abs(current_ms - self.start_marker_ms) < margin_ms or abs(current_ms - self.end_marker_ms) < margin_ms:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.SizeHorCursor))
            return

        on_edge = False
        inside_block = False
        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(event.position().toPoint()):
                inside_block = True
                if evt.get("zone", -1) != 2 and not evt.get("single_frame", False):
                    if abs(pos_x - rect.left()) <= self.resize_margin or abs(pos_x - rect.right()) <= self.resize_margin:
                        on_edge = True
                break

        if on_edge:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.SizeHorCursor))
        elif inside_block:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.SizeAllCursor))
        else:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event):
        """Finalise le redimensionnement/déplacement et émet les signaux appropriés."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self.active_resize_event:
                self.eventResized.emit(self.active_resize_event)
                self.active_resize_event = None
            if self.active_move_event:
                self.eventMoved.emit(self.active_move_event)
                self.active_move_event = None
            if hasattr(self, 'active_resize_marker'):
                del self.active_resize_marker
            if self.is_dragging:
                self.is_dragging = False
                self.sliderMoved.emit(self.current_pos)
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))
            self.update()

    def wheelEvent(self, event):
        """Zoom la timeline à la molette et conserve l'ancre temporelle sous le curseur."""
        if self.total_duration <= 0:
            return

        # Chercher la scroll area parente
        scroll_area = None
        p = self.parent()
        while p is not None:
            if isinstance(p, QtWidgets.QScrollArea):
                scroll_area = p
                break
            p = p.parent()

        scroll_offset = scroll_area.horizontalScrollBar().value() if scroll_area else 0
        # pos_x dans l'espace du contenu (coordonnée widget + scroll courant)
        pos_x_content = event.position().x() + scroll_offset
        current_width = self.min_zoomed_width()
        time_ratio = pos_x_content / current_width if current_width > 0 else 0
        target_time = time_ratio * self.total_duration

        zoom_step = 1.2
        old_zoom = self.zoom_factor
        if event.angleDelta().y() > 0:
            self.zoom_factor *= zoom_step
        else:
            self.zoom_factor /= zoom_step
        self.zoom_factor = max(1.0, min(self.zoom_factor, 10.0))

        if self.zoom_factor == old_zoom:
            return

        self.zoomChanged.emit(self.zoom_factor)
        self.setMinimumWidth(self.min_zoomed_width())
        self.updateGeometry()

        new_width = self.min_zoomed_width()
        new_pos_x_content = (target_time / self.total_duration) * new_width

        if scroll_area:
            # Repositionner pour que le temps sous le curseur reste au même endroit
            new_scroll = int(new_pos_x_content - event.position().x())
            QtCore.QTimer.singleShot(1, lambda: (
                scroll_area.horizontalScrollBar().setValue(new_scroll),
            ))

        self.timeChanged.emit(self.current_pos)
        self.update()

    def calculate_and_emit_position(self, mouse_x):
        """Convertit la position souris en millisecondes et émet timeChanged."""
        w = self.min_zoomed_width()
        if w <= 0:
            return
        ratio = max(0.0, min(mouse_x / w, 1.0))
        target_ms = int(ratio * self.total_duration)
        self.current_pos = target_ms
        self.timeChanged.emit(target_ms)
        self.update()

    def _format_ms(self, ms):
        """Formate un entier en millisecondes au format MM:SS ou HH:MM:SS."""
        if callable(ms):
            ms = ms()
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            return "00:00:00"
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = ms // 3600000
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def get_event_at_position(self, pos: QtCore.QPoint) -> dict | None:
        """Retourne le dict d'événement sous pos, ou None si aucun ne contient ce point."""
        if not hasattr(self, 'rects_evenements') or not self.rects_evenements:
            return None
        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(int(pos.x()), int(pos.y())):
                return evt
        return None
