from PyQt6 import QtCore, QtGui, QtWidgets

class VideoTimeline(QtWidgets.QWidget):
    """
    Widget de Timeline personnalisé avec support du Zoom horizontal 
    ET édition interactive (étirement/rétrécissement ET déplacement horizontal).
    """
    sliderMoved = QtCore.pyqtSignal(int)
    timeChanged = QtCore.pyqtSignal(int)
    eventResized = QtCore.pyqtSignal(dict) 
    # Nouveau signal émis quand un événement a fini d'être déplacé
    eventMoved = QtCore.pyqtSignal(dict)
    eventSelected = QtCore.pyqtSignal(object)  # object permet dict ou None
    zoomChanged = QtCore.pyqtSignal(float)  # Émis quand le zoom change

    def __init__(self, events=None, parent=None, zone_definitions=None):
        super().__init__(parent)
        self.events = events if events is not None else []
        # zone_definitions: list of dict {label, color} to draw colored zone rows.
        # If None or empty -> render as a single plain track (no colored zones).
        self.zone_definitions = zone_definitions if zone_definitions is not None else []
        self.current_pos = 0   
        self.total_duration = 0 
        self.is_dragging = False
        self.zoom_factor = 1.0  
        
        # --- SEGMENTS (ZONES ENTRE DÉCOLLAGE ET ATTERRISSAGE) ---
        self.segments = []  # Liste des segments calculés automatiquement

        # --- VARIABLE POUR LA SURBRILLANCE ---
        self.selected_event_dict = None  # Stocke l'événement sélectionné dans l'arbre

        # --- VARIABLES POUR L'ÉDITION DES ÉVÉNEMENTS ---
        self.resize_margin = 6           # Zone de tolérance en pixels pour attraper le bord
        self.active_resize_event = None  # L'événement en cours de modification de taille
        self.resize_edge = None          # "left" ou "right"
        
        # --- VARIABLES POUR LE DÉPLACEMENT DE L'ÉVÉNEMENT ---
        self.active_move_event = None    # L'événement en cours de déplacement horizontal
        self.drag_start_mouse_x = 0      # Position X initiale de la souris au clic
        self.drag_start_event_start = 0  # Temps "start" initial de l'événement au clic
        self.drag_start_event_end = 0    # Temps "end" initial de l'événement au clic

        self.rects_evenements = {}       # Mémorise les positions des rectangles dessinés

        self.setMinimumHeight(140)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True) 

    def _clamp_int(self, value):
        try:
            val = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        if val < -2147483648: return -2147483648
        if val > 2147483647: return 2147483647
        return val

    def set_zoom(self, factor):
        self.zoom_factor = max(1.0, factor)
        self.updateGeometry()
        self.update()

    def min_largeur_zoomee(self):
        base_width = self.parent().width() if self.parent() else self.width()
        return int(base_width * self.zoom_factor)

    def sizeHint(self):
        return QtCore.QSize(self.min_largeur_zoomee(), self.height())

    def set_total_duration(self, duration_ms):
        self.total_duration = duration_ms
        self.updateGeometry()
        self.update()

    def set_current_position(self, position_ms):
        if not self.is_dragging and not self.active_resize_event and not self.active_move_event:
            self.current_pos = position_ms
            self.update()

    def set_selected_event(self, event_dict):
        """Définit l'événement à mettre en surbillance et rafraîchit le widget"""
        self.selected_event_dict = event_dict
        self.update()
    
    def calculate_segments(self):
        """Calcule automatiquement les segments entre atterrissage et décollage"""
        self.segments = []
        
        # Chercher les événements "décollage" et "atterrissage"
        decollages = []
        atterrissages = []
        
        for evt in self.events:
            titre = evt.get("title", "").lower()
            if "atterrissage" in titre or "landing" in titre:
                atterrissages.append(evt)
            elif "décollage" in titre or "takeoff" in titre:
                decollages.append(evt)
        
        # Créer des segments entre chaque atterrissage et le décollage qui suit
        for atterrissage in atterrissages:
            # Trouver le décollage qui suit cet atterrissage
            start_temps = atterrissage.get("end", atterrissage.get("start", 0))
            
            # Chercher le premier décollage après l'atterrissage
            decollage_suivant = None
            for decollage in decollages:
                decollage_temps = decollage.get("start", decollage.get("end", 0))
                if decollage_temps > start_temps:
                    if decollage_suivant is None or decollage_temps < decollage_suivant.get("start", decollage_suivant.get("end", 0)):
                        decollage_suivant = decollage
            
            # Si on a trouvé un décollage, créer un segment
            if decollage_suivant:
                end_temps = decollage_suivant.get("start", decollage_suivant.get("end", 0))
                segment = {
                    "start": start_temps,
                    "end": end_temps,
                    "zone": atterrissage.get("zone", 0)  # Même zone que l'atterrissage
                }
                self.segments.append(segment)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Calculer les segments avant de peindre
        self.calculate_segments()

        largeur = self.min_largeur_zoomee()
        hauteur_totale = self.height()
        duree_totale = self.total_duration if self.total_duration > 0 else 1

        painter.fillRect(0, 0, largeur, hauteur_totale, QtGui.QColor("#141414"))

        hauteur_piste = 24  
        espace_entre_pistes = 6
        y_depart_pistes = 25  
        pistes_occupees = []

        # Use provided zone_definitions if any, otherwise render a single plain track
        zone_definitions = self.zone_definitions or []
        if not zone_definitions:
            zone_count = 1
            zone_spacing = 0
            zone_top_margin = 10
            zone_height = max(30, hauteur_totale - 2 * zone_top_margin)
            zone_rows = {0: []}
        else:
            zone_count = len(zone_definitions)
            zone_spacing = 10
            zone_top_margin = 10
            zone_height = max(50, (hauteur_totale - zone_top_margin - (zone_count - 1) * zone_spacing) // zone_count)
            zone_rows = {i: [] for i in range(zone_count)}

            for zone_index, zone in enumerate(zone_definitions):
                y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)
                painter.fillRect(0, y_zone, largeur, zone_height, zone["color"])
                painter.setPen(QtGui.QPen(QtGui.QColor("#3d3d3d"), 1))
                painter.drawLine(0, y_zone, largeur, y_zone)
                painter.drawLine(0, y_zone + zone_height, largeur, y_zone + zone_height)
                painter.setPen(QtGui.QColor("white"))
                font_zone = painter.font()
                font_zone.setPointSize(9)
                painter.setFont(font_zone)
                painter.drawText(8, y_zone + 16, zone["label"])

        self.rects_evenements.clear()
        
        # --- DESSINER LES SEGMENTS (ZONES ENTRE DÉCOLLAGE ET ATTERRISSAGE) ---
        for segment in self.segments:
            start_ms = segment.get("start", 0)
            end_ms = segment.get("end", 0)
            
            x_start = self._clamp_int((start_ms / duree_totale) * largeur)
            x_end = self._clamp_int((end_ms / duree_totale) * largeur)
            
            zone_index = segment.get("zone", 0)
            zone_index = max(0, min(zone_index, zone_count - 1))
            y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)
            
            # Dessiner le segment comme une bande semi-transparente
            segment_rect = QtCore.QRect(x_start, y_zone, max(1, x_end - x_start), zone_height)
            couleur_segment = QtGui.QColor(100, 200, 255, 60)  # Bleu semi-transparent
            painter.fillRect(segment_rect, couleur_segment)
            
            # Bordure du segment
            painter.setPen(QtGui.QPen(QtGui.QColor(100, 200, 255, 150), 1))
            painter.drawRect(segment_rect)

        for idx, evt in enumerate(self.events):
            start_ms = evt.get("start", 0)
            end_ms = evt.get("end", 0)
            titre = evt.get("title", "")
            type_evt = evt.get("type", "")

            x_start = self._clamp_int((start_ms / duree_totale) * largeur)

            if type_evt != "custom_event":
                couleur = "#ff3b30" if type_evt.lower() == "rotation_360" else "white"
                largeur_ligne = 2.5 if type_evt.lower() == "rotation_360" else 1.5
                pen_pointille = QtGui.QPen(QtGui.QColor(couleur), largeur_ligne)
                pen_pointille.setStyle(QtCore.Qt.PenStyle.DashLine)
                painter.setPen(pen_pointille)
                x_start = self._clamp_int(x_start)
                painter.drawLine(x_start, 0, x_start, hauteur_totale)
                continue 

            x_end = self._clamp_int((end_ms / duree_totale) * largeur)
            largeur_rect = self._clamp_int(max(x_end - x_start, 8))
            txt_start = self._format_ms(start_ms)
            txt_end = self._format_ms(end_ms)

            zone_index = evt.get("zone", 0)
            zone_index = max(0, min(zone_index, zone_count - 1))
            y_zone = zone_top_margin + zone_index * (zone_height + zone_spacing)

            row_index = 0
            while row_index < len(zone_rows[zone_index]):
                overlap = False
                for interval in zone_rows[zone_index][row_index]:
                    if not (x_end <= interval[0] or x_start >= interval[1]):
                        overlap = True
                        break
                if not overlap: break
                row_index += 1

            if row_index >= len(zone_rows[zone_index]):
                zone_rows[zone_index].append([])
            zone_rows[zone_index][row_index].append((x_start, x_end))

            y_position = y_zone + 10 + row_index * (hauteur_piste + 4)
            if y_position + hauteur_piste > y_zone + zone_height - 5:
                y_position = y_zone + 10

            rect_box = QtCore.QRect(self._clamp_int(x_start), y_position, largeur_rect, hauteur_piste)
            self.rects_evenements[idx] = (evt, rect_box)

            if zone_index == 0:
                couleur_fond = QtGui.QColor("#20415D")
                couleur_bord = QtGui.QColor("#20415D")
            elif zone_index == 1:
                couleur_fond = QtGui.QColor("#2778A2")
                couleur_bord = QtGui.QColor("#2778A2")
            else:
                couleur_fond = QtGui.QColor("#D94F38")
                couleur_bord = QtGui.QColor("#D94F38") 

            # Vérification de la sélection pour la mise en surbillance
            est_selectionne = False
            if self.selected_event_dict is not None:
                if evt.get("title") == self.selected_event_dict.get("title") and evt.get("start") == self.selected_event_dict.get("start"):
                    est_selectionne = True

            chemin_rect = QtGui.QPainterPath()
            chemin_rect.addRoundedRect(QtCore.QRectF(rect_box), 4, 4)
            
            painter.fillPath(chemin_rect, couleur_fond)
            
            if est_selectionne:
                # Bordure jaune épaisse si sélectionné
                painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 3))
            else:
                painter.setPen(QtGui.QPen(couleur_bord, 1))
                
            painter.drawPath(chemin_rect)

            if largeur_rect > 15 and zone_index != 2:
                painter.setPen(QtGui.QColor(255, 255, 255, 100))
                painter.drawLine(x_start + 2, y_position + 6, x_start + 2, y_position + hauteur_piste - 6)
                painter.drawLine(x_end - 2, y_position + 6, x_end - 2, y_position + hauteur_piste - 6)

            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)

            if largeur_rect > 70:
                texte_complet = f"[{txt_start}] {titre} [{txt_end}]"
                painter.setPen(QtGui.QColor("white"))
                texte_affiche = painter.fontMetrics().elidedText(texte_complet, QtCore.Qt.TextElideMode.ElideRight, largeur_rect - 10)
                painter.drawText(QtCore.QRect(x_start + 5, y_position, largeur_rect - 10, hauteur_piste), 
                                 QtCore.Qt.AlignmentFlag.AlignCenter, texte_affiche)
            elif largeur_rect > 35:
                painter.setPen(QtGui.QColor("white"))
                texte_affiche = painter.fontMetrics().elidedText(titre, QtCore.Qt.TextElideMode.ElideRight, largeur_rect - 6)
                painter.drawText(QtCore.QRect(x_start + 3, y_position, largeur_rect - 6, hauteur_piste), 
                                 QtCore.Qt.AlignmentFlag.AlignCenter, texte_affiche)

        x_curseur = self._clamp_int((self.current_pos / duree_totale) * largeur)
        pen_curseur = QtGui.QPen(QtGui.QColor("#0816b0"), 2)
        painter.setPen(pen_curseur)
        painter.drawLine(x_curseur, 0, x_curseur, hauteur_totale)

        txt_instantane = self._format_ms(self.current_pos)
        font_chrono = painter.font()
        font_chrono.setPointSize(9)
        font_chrono.setBold(True)
        painter.setFont(font_chrono)
        painter.setPen(QtGui.QColor("#ff3b30"))

        largeur_txt = painter.fontMetrics().horizontalAdvance(txt_instantane)
        x_texte = x_curseur - (largeur_txt // 2)
        x_texte = max(5, min(x_texte, largeur - largeur_txt - 5))
        painter.drawText(x_texte, 15, txt_instantane)

        painter.setBrush(QtGui.QColor("#ff3b30"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(QtCore.QPoint(self._clamp_int(x_curseur), 18), 4, 4)
        painter.end()


    # =========================================================================
    # --- SYSTÈME DES INTERACTIONS SOURIS ---
    # =========================================================================

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self.total_duration <= 0:
            return

        pos_x = event.position().x()
        pos_y = event.position().y()

        # Priorité 1 : Est-ce qu'on clique à l'intérieur du rectangle d'un événement ?
        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(int(pos_x), int(pos_y)):
                
                # Mettre à jour la sélection graphique immédiate au clic
                self.set_selected_event(evt)
                
                # NOUVEAU : On émet le signal vers l'extérieur pour l'arbre
                self.eventSelected.emit(evt)
                
                # S'il s'agit d'un événement ponctuel/single-frame, pas de redimensionnement possible
                if evt.get("zone", -1) == 2 or evt.get("single_frame", False) or evt.get("start") == evt.get("end"):
                    evt["_old_start"] = evt.get("start")
                    evt["_old_end"] = evt.get("end")
                    self.active_move_event = evt
                    self.drag_start_mouse_x = pos_x
                    self.drag_start_event_start = evt["start"]
                    self.drag_start_event_end = evt["end"]
                    return

                # CAS A : Détection des bords gauches/droits pour REDIMENSIONNER
                if abs(pos_x - rect.left()) <= self.resize_margin:
                    evt["_old_start"] = evt.get("start")
                    evt["_old_end"] = evt.get("end")
                    self.active_resize_event = evt
                    self.resize_edge = "left"
                    return
                elif abs(pos_x - rect.right()) <= self.resize_margin:
                    evt["_old_start"] = evt.get("start")
                    evt["_old_end"] = evt.get("end")
                    self.active_resize_event = evt
                    self.resize_edge = "right"
                    return
                
                # CAS B : Clic au centre du bloc -> MODE DÉPLACEMENT HORIZONTAL
                else:
                    self.active_move_event = evt
                    self.drag_start_mouse_x = pos_x
                    self.drag_start_event_start = evt["start"]
                    self.drag_start_event_end = evt["end"]
                    return

        # Priorité 2 : Si aucun bloc n'a été touché, alors on décoche la sélection
        self.set_selected_event(None)
        # NOUVEAU : On signale à l'arbre de tout désélectionner (on envoie None)
        self.eventSelected.emit(None) 
        
        self.is_dragging = True
        self.calculer_et_emettre_position(pos_x)

    def mouseMoveEvent(self, event):
        pos_x = event.position().x()
        pos_y = event.position().y()
        largeur = self.min_largeur_zoomee()
        duree_totale = self.total_duration if self.total_duration > 0 else 1

        # ACTION 1 : On est en train d'étirer/rétrécir un bord (Resize)
        if self.active_resize_event:
            ratio = max(0.0, min(pos_x / largeur, 1.0))
            nouveau_temps_ms = int(ratio * duree_totale)

            if self.resize_edge == "left":
                if nouveau_temps_ms < self.active_resize_event["end"]:
                    self.active_resize_event["start"] = nouveau_temps_ms
            elif self.resize_edge == "right":
                if nouveau_temps_ms > self.active_resize_event["start"]:
                    self.active_resize_event["end"] = nouveau_temps_ms

            self.update()
            return

        # ACTION 2 : On est en train de déplacer tout l'événement horizontalement (Move)
        if self.active_move_event:
            delta_pixels = pos_x - self.drag_start_mouse_x
            delta_ms = int((delta_pixels / largeur) * duree_totale)

            nouveau_start = self.drag_start_event_start + delta_ms
            nouveau_end = self.drag_start_event_end + delta_ms
            duree_bloc = self.drag_start_event_end - self.drag_start_event_start

            if nouveau_start < 0:
                nouveau_start = 0
                nouveau_end = duree_bloc
            elif nouveau_end > self.total_duration:
                nouveau_end = self.total_duration
                nouveau_start = self.total_duration - duree_bloc

            self.active_move_event["start"] = nouveau_start
            self.active_move_event["end"] = nouveau_end

            self.update()
            return

        # ACTION 3 : On déplace le curseur de lecture rouge classique
        if self.is_dragging:
            self.calculer_et_emettre_position(pos_x)
            return

        # ACTION 4 : Modification visuelle du curseur lors du simple survol (Hover)
        sur_un_bord = False
        dans_un_bloc = False
        
        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(int(pos_x), int(pos_y)):
                dans_un_bloc = True
                if evt.get("zone", -1) != 2 and not evt.get("single_frame", False) and evt.get("start") != evt.get("end"):
                    if abs(pos_x - rect.left()) <= self.resize_margin or abs(pos_x - rect.right()) <= self.resize_margin:
                        sur_un_bord = True
                break
        
        if sur_un_bord:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.SizeHorCursor))   # Curseur ↔ (Resize)
        elif dans_un_bloc:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.SizeAllCursor))   # Curseur ✚ (Déplacement)
        else:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))     # Curseur standard

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            
            # Si on finit d'étirer un bloc
            if self.active_resize_event:
                self.eventResized.emit(self.active_resize_event)
                self.active_resize_event = None
                self.resize_edge = None
            
            # Si on finit de déplacer horizontalement un bloc
            if self.active_move_event:
                self.eventMoved.emit(self.active_move_event)
                self.active_move_event = None
            
            # Si on lâche le curseur rouge de lecture
            if self.is_dragging:
                self.is_dragging = False
                self.sliderMoved.emit(self.current_pos)
            
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))
            self.update()

    def wheelEvent(self, event):
        """Gère le zoom à la molette de la souris tout en gardant la position sous la souris"""
        if self.total_duration <= 0:
            return
        
        # Récupérer la position de la souris sur la timeline
        pos_x = event.position().x()
        largeur_actuelle = self.min_largeur_zoomee()
        
        # Calculer le ratio de temps à cette position AVANT zoom
        ratio_temps = pos_x / largeur_actuelle if largeur_actuelle > 0 else 0
        temps_a_position = ratio_temps * self.total_duration
        
        # Calculer le nouveau zoom_factor selon la direction de la molette
        zoom_step = 1.2  # Facteur de zoom (1.2 = +20% par cran)
        if event.angleDelta().y() > 0:  # Molette vers le haut = zoom in
            self.zoom_factor *= zoom_step
        else:  # Molette vers le bas = zoom out
            self.zoom_factor /= zoom_step
        
        # Limiter le zoom entre 1.0 (minimal) et 10.0 (maximal)
        ancien_zoom = self.zoom_factor
        self.zoom_factor = max(1.0, min(self.zoom_factor, 10.0))
        
        # Si le zoom a réellement changé, émettre le signal
        if self.zoom_factor != ancien_zoom:
            self.zoomChanged.emit(self.zoom_factor)
        
        # Recalculer la nouvelle largeur après zoom
        nouvelle_largeur = self.min_largeur_zoomee()
        
        # Calculer la nouvelle position du curseur pour garder la même position temporelle sous la souris
        nouvelle_pos_x = (temps_a_position / self.total_duration) * nouvelle_largeur if self.total_duration > 0 else 0
        
        # Calculer le décalage de scroll requis (parent doit avoir un scroll)
        parent = self.parent()
        if isinstance(parent, QtWidgets.QScrollArea):
            # Nouvelle position X de la souris en coordonnées widget
            delta_scroll = int(nouvelle_pos_x - pos_x)
            current_scroll = parent.horizontalScrollBar().value()
            parent.horizontalScrollBar().setValue(current_scroll + delta_scroll)
        
        # Émettre le signal de changement de position pour mettre à jour le slider
        self.timeChanged.emit(self.current_pos)
        
        # Recalculer la géométrie et rafraîchir
        self.updateGeometry()
        self.update()

    # =========================================================================

    def calculer_et_emettre_position(self, mouse_x):
        w = self.min_largeur_zoomee()
        if w <= 0: return
        ratio = max(0.0, min(mouse_x / w, 1.0))
        target_ms = int(ratio * self.total_duration)
        
        self.current_pos = target_ms
        self.timeChanged.emit(target_ms)
        self.update()

    def _format_ms(self, ms):
        secondes = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        heures = (ms // 3600000)
        if heures > 0:
            return f"{heures:02d}:{minutes:02d}:{secondes:02d}"
        return f"{minutes:02d}:{secondes:02d}"
    
    def get_event_at_position(self, pos: QtCore.QPoint) -> dict | None:
        if not hasattr(self, 'rects_evenements') or not self.rects_evenements:
            return None
        pos_x = pos.x()
        pos_y = pos.y()
        for idx, (evt, rect) in self.rects_evenements.items():
            if rect.contains(int(pos_x), int(pos_y)):
                return evt
        return None