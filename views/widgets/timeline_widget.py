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

        self.setMinimumHeight(140)
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
        self.updateGeometry()
        self.update()

    def min_zoomed_width(self):
        """Retourne la largeur effective en pixels (largeur parent × zoom_factor)."""
        base_width = self.parent().width() if self.parent() else self.width()
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

    def paintEvent(self, event):
        """Dessine les zones, segments, événements, curseur de lecture et marqueurs d'export."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        self.calculate_segments()

        width = self.min_zoomed_width()
        total_height = self.height()
        total_duration = self.total_duration if self.total_duration > 0 else 1

        painter.fillRect(0, 0, width, total_height, QtGui.QColor("#141414"))

        track_height = 24
        zone_definitions = self.zone_definitions or []

        if not zone_definitions:
            zone_count = 1
            zone_spacing = 0
            zone_top_margin = 10
            zone_height = max(30, total_height - 2 * zone_top_margin)
            zone_rows = {0: []}
        else:
            zone_count = len(zone_definitions)
            zone_spacing = 10
            zone_top_margin = 10
            zone_height = max(50, (total_height - zone_top_margin - (zone_count - 1) * zone_spacing) // zone_count)
            zone_rows = {i: [] for i in range(zone_count)}

            for zone_index, zone in enumerate(zone_definitions):
                y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)
                painter.fillRect(0, y_zone, width, zone_height, zone["color"])
                painter.setPen(QtGui.QPen(QtGui.QColor("#3d3d3d"), 1))
                painter.drawLine(0, y_zone, width, y_zone)
                painter.drawLine(0, y_zone + zone_height, width, y_zone + zone_height)
                painter.setPen(QtGui.QColor("white"))
                font_zone = painter.font()
                font_zone.setPointSize(9)
                painter.setFont(font_zone)
                painter.drawText(8, y_zone + 16, zone["label"])

        self.rects_evenements.clear()

        for segment in self.segments:
            start_ms = segment.get("start", 0)
            end_ms = segment.get("end", 0)
            x_start = self._clamp_int((start_ms / total_duration) * width)
            x_end = self._clamp_int((end_ms / total_duration) * width)
            zone_index = max(0, min(segment.get("zone", 0), zone_count - 1))
            y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)
            segment_rect = QtCore.QRect(x_start, y_zone, max(1, x_end - x_start), zone_height)
            painter.fillRect(segment_rect, QtGui.QColor(100, 200, 255, 60))
            painter.setPen(QtGui.QPen(QtGui.QColor(100, 200, 255, 150), 1))
            painter.drawRect(segment_rect)

        for idx, evt in enumerate(self.events):
            start_ms = evt.get("start", 0)
            end_ms = evt.get("end", 0)
            title = evt.get("title", "")
            evt_type = evt.get("type", "")

            x_start = self._clamp_int((start_ms / total_duration) * width)

            if evt_type != "custom_event":
                is_rotation_360 = "360" in evt_type.lower()
                color = "#ff3b30" if is_rotation_360 else "white"
                line_width = 2.5 if is_rotation_360 else 1.5
                dash_pen = QtGui.QPen(QtGui.QColor(color), line_width)
                dash_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
                painter.setPen(dash_pen)
                painter.drawLine(self._clamp_int(x_start), 0, self._clamp_int(x_start), total_height)
                continue

            x_end = self._clamp_int((end_ms / total_duration) * width)
            rect_width = self._clamp_int(max(x_end - x_start, 8))
            txt_start = self._format_ms(start_ms)
            txt_end = self._format_ms(end_ms)

            zone_index = max(0, min(evt.get("zone", 0), zone_count - 1))
            y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)

            row_index = 0
            while row_index < len(zone_rows[zone_index]):
                overlap = False
                for interval in zone_rows[zone_index][row_index]:
                    if not (x_end <= interval[0] or x_start >= interval[1]):
                        overlap = True
                        break
                if not overlap:
                    break
                row_index += 1

            if row_index >= len(zone_rows[zone_index]):
                zone_rows[zone_index].append([])
            zone_rows[zone_index][row_index].append((x_start, x_end))

            y_position = y_zone + 10 + row_index * (track_height + 4)
            if y_position + track_height > y_zone + zone_height - 5:
                y_position = y_zone + 10

            rect_box = QtCore.QRect(self._clamp_int(x_start), y_position, rect_width, track_height)
            self.rects_evenements[idx] = (evt, rect_box)

            if zone_index == 0:
                bg_color = QtGui.QColor("#20415D")
                border_color = QtGui.QColor("#20415D")
            elif zone_index == 1:
                bg_color = QtGui.QColor("#2778A2")
                border_color = QtGui.QColor("#2778A2")
            else:
                bg_color = QtGui.QColor("#D94F38")
                border_color = QtGui.QColor("#D94F38")

            is_selected = (
                self.selected_event_dict is not None
                and evt.get("title") == self.selected_event_dict.get("title")
                and evt.get("start") == self.selected_event_dict.get("start")
            )

            rect_path = QtGui.QPainterPath()
            rect_path.addRoundedRect(QtCore.QRectF(rect_box), 4, 4)
            painter.fillPath(rect_path, bg_color)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff") if is_selected else border_color, 3 if is_selected else 1))
            painter.drawPath(rect_path)

            if rect_width > 15 and zone_index != 2:
                painter.setPen(QtGui.QColor(255, 255, 255, 100))
                painter.drawLine(x_start + 2, y_position + 6, x_start + 2, y_position + track_height - 6)
                painter.drawLine(x_end - 2, y_position + 6, x_end - 2, y_position + track_height - 6)

            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)

            if rect_width > 70:
                full_text = f"[{txt_start}] {title} [{txt_end}]"
                painter.setPen(QtGui.QColor("white"))
                displayed_text = painter.fontMetrics().elidedText(full_text, QtCore.Qt.TextElideMode.ElideRight, rect_width - 10)
                painter.drawText(QtCore.QRect(x_start + 5, y_position, rect_width - 10, track_height),
                                 QtCore.Qt.AlignmentFlag.AlignCenter, displayed_text)
            elif rect_width > 35:
                painter.setPen(QtGui.QColor("white"))
                displayed_text = painter.fontMetrics().elidedText(title, QtCore.Qt.TextElideMode.ElideRight, rect_width - 6)
                painter.drawText(QtCore.QRect(x_start + 3, y_position, rect_width - 6, track_height),
                                 QtCore.Qt.AlignmentFlag.AlignCenter, displayed_text)

        x_cursor = self._clamp_int((self.current_pos / total_duration) * width)
        painter.setPen(QtGui.QPen(QtGui.QColor("#0816b0"), 2))
        painter.drawLine(x_cursor, 0, x_cursor, total_height)

        current_timestamp = self._format_ms(self.current_pos)
        chrono_font = painter.font()
        chrono_font.setPointSize(9)
        chrono_font.setBold(True)
        painter.setFont(chrono_font)
        painter.setPen(QtGui.QColor("#ff3b30"))
        txt_width = painter.fontMetrics().horizontalAdvance(current_timestamp)
        x_text = max(5, min(x_cursor - (txt_width // 2), width - txt_width - 5))
        painter.drawText(x_text, 15, current_timestamp)
        painter.setBrush(QtGui.QColor("#ff3b30"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(QtCore.QPoint(self._clamp_int(x_cursor), 18), 4, 4)

        if self.start_marker_ms > 0 or self.end_marker_ms > 0:
            if self.start_marker_ms > 0:
                x_sm = self._clamp_int((self.start_marker_ms / total_duration) * width)
                painter.setPen(QtGui.QPen(QtGui.QColor("#27ae60"), 3))
                painter.drawLine(x_sm, 0, x_sm, total_height)
                painter.setBrush(QtGui.QColor("#27ae60"))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon([QtCore.QPoint(x_sm, 8), QtCore.QPoint(x_sm - 5, 0), QtCore.QPoint(x_sm + 5, 0)])
            if self.end_marker_ms > 0:
                x_em = self._clamp_int((self.end_marker_ms / total_duration) * width)
                painter.setPen(QtGui.QPen(QtGui.QColor("#e74c3c"), 3))
                painter.drawLine(x_em, 0, x_em, total_height)
                painter.setBrush(QtGui.QColor("#e74c3c"))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon([QtCore.QPoint(x_em, total_height - 8),
                                     QtCore.QPoint(x_em - 5, total_height),
                                     QtCore.QPoint(x_em + 5, total_height)])

        painter.end()

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

        pos_x_local = event.position().x()
        current_width = self.min_zoomed_width()
        time_ratio = pos_x_local / current_width if current_width > 0 else 0
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
        self.updateGeometry()
        if self.parent():
            self.parent().adjustSize()

        new_width = self.min_zoomed_width()
        new_pos_x_local = (target_time / self.total_duration) * new_width

        scroll_area = None
        p = self.parent()
        while p is not None:
            if isinstance(p, QtWidgets.QScrollArea):
                scroll_area = p
                break
            p = p.parent()

        if scroll_area:
            delta_scroll = int(new_pos_x_local - pos_x_local)
            horizontal_bar = scroll_area.horizontalScrollBar()
            horizontal_bar.setValue(horizontal_bar.value() + delta_scroll)

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
