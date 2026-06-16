import os
import cv2

from PyQt6 import QtWidgets, QtCore, QtGui

from services.motor_service import get_motor_stable_timestamps
from services.video_service import check_stereo_status
from services.export_service import VideoSegmentationWorker
from views.widgets.embedded_player import EmbeddedVideoPlayer
from views.dialogs.capture_dialog import CaptureDialog


class ExtractionController:
    """Contrôleur de la page Extraction : découpe vidéo, capture d'image et gestion des livrables."""

    def __init__(self, widget: QtWidgets.QWidget, video_model):
        """Initialise le player, l'arbre vidéo, le panneau de paramètres et le modèle de livrables."""
        self.widget = widget
        self.video_model = video_model
        self.current_is_stereo = False
        self.current_video_payload = None
        self.current_video_path = None
        self.start_ms = 0
        self.end_ms = 0
        self.segmentation_worker = None
        self.last_raw_frame = None
        self.current_processed_frame = None
        self.current_capture_name = ""
        self.last_segment_name = ""

        children = {w.objectName(): w for w in self.widget.findChildren(QtWidgets.QWidget)}
        self.param_container = children.get("param_container")
        self.lecteur_timeline_container_2 = children.get("lecteur_timeline_container_2")
        self.tree_videos_2 = children.get("tree_videos_2")
        self.tree_segment_capture_container = children.get("tree_segment_capture_container")

        self.deliverables_model = QtGui.QStandardItemModel()
        self.deliverables_model.setHorizontalHeaderLabels(["Nom", "Taille", "Type"])

        if self.tree_segment_capture_container:
            self.tree_segment_capture_container.setModel(self.deliverables_model)
            self.tree_segment_capture_container.setIconSize(QtCore.QSize(64, 48))

        self.video_player = EmbeddedVideoPlayer(zone_definitions=None)
        self._setup_ui()

    def _setup_ui(self):
        """Monte le player, connecte l'arbre vidéo et construit le panneau de paramètres."""
        if self.lecteur_timeline_container_2:
            layout = self.lecteur_timeline_container_2.layout() or QtWidgets.QVBoxLayout(self.lecteur_timeline_container_2)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.video_player)

        if self.tree_videos_2:
            self.tree_videos_2.clicked.connect(self.on_video_selected_treeview)
            if self.video_model:
                self.tree_videos_2.setModel(self.video_model)
            else:
                self.show_no_campaign_message()

        if self.param_container:
            self._fill_param_container()

        if self.tree_segment_capture_container:
            self.show_no_cap_seg_message()

        self.video_player.timeline.markersChanged.connect(self.on_timeline_markers_moved)

    def load_campaign_videos(self, model):
        """Remplace le modèle vidéo après changement de campagne."""
        self.video_model = model
        if self.tree_videos_2:
            self.tree_videos_2.setModel(self.video_model)

    def select_video_by_name(self, video_name: str):
        """Sélectionne une vidéo dans l'arbre depuis son nom (appel depuis la carte)."""
        if not self.tree_videos_2 or not self.video_model:
            return
        model = self.tree_videos_2.model()
        if not model:
            return
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            if item and item.text() == video_name:
                index = model.indexFromItem(item)
                self.tree_videos_2.selectionModel().setCurrentIndex(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect |
                    QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.tree_videos_2.scrollTo(index)
                self.on_video_selected_treeview(index)
                break

    def refresh_video_list(self):
        """Rafraîchit l'arbre vidéo (appelé lors des changements de page)."""
        if hasattr(self, 'tree_videos_2') and self.tree_videos_2:
            if self.video_model and self.video_model.rowCount() > 0:
                self.tree_videos_2.setModel(self.video_model)
                self.tree_videos_2.viewport().update()
            else:
                self.show_no_campaign_message()

    def on_video_selected_treeview(self, index: QtCore.QModelIndex):
        """Charge la vidéo sélectionnée, la télémétrie CSV et les événements moteur."""
        if not index.isValid():
            return
        model = self.tree_videos_2.model()
        item = model.itemFromIndex(index.siblingAtColumn(0))
        if not item:
            return

        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if video_path and os.path.exists(video_path):
            is_stereo, video_payload = check_stereo_status(video_path)
            self.current_is_stereo = is_stereo
            self.current_video_payload = video_payload
            self.current_video_path = video_path

            if hasattr(self, 'btn_capture_main'):
                self.btn_capture_main.setVisible(not is_stereo)
                self.btn_capture_L.setVisible(is_stereo)
                self.btn_capture_R.setVisible(is_stereo)

            self.update_export_buttons_visibility()
            self.start_ms = 0
            self.end_ms = 0

            video_dir = os.path.dirname(video_path)
            csv_system = os.path.join(video_dir, "systemEvent.csv")
            motor_events = []
            if os.path.exists(csv_system):
                try:
                    motor_events = get_motor_stable_timestamps(csv_system, delay=6.0)
                except Exception as e:
                    print(f"[MOTEURS] Erreur : {e}")

            csv_telemetry = video_path.replace(".mp4", ".csv")
            if os.path.exists(csv_telemetry):
                self.video_player.load_dynamic_metadata(csv_telemetry)
            else:
                self.video_player.df_telemetry = None

            if hasattr(self.video_player, 'load_video_and_events'):
                self.video_player.load_video_and_events(video_payload, motor_events, is_stereo=is_stereo)

            self.update_segmentation_display()

    def _fill_param_container(self):
        """Construit le panneau de paramètres (groupes Découpe, Capture, Export)."""
        if not self.param_container.layout():
            QtWidgets.QVBoxLayout(self.param_container)

        layout = self.param_container.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        layout.addWidget(self._group_segmentation())
        layout.addWidget(self._group_frame_capture())

        self.group_export = QtWidgets.QGroupBox("Export Vidéo")
        export_vbox = QtWidgets.QVBoxLayout(self.group_export)

        self.btn_export_main = QtWidgets.QPushButton("EXPORTER LE SEGMENT")
        self.btn_export_main.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; padding: 12px;"
        )
        self.btn_export_main.clicked.connect(lambda: self.on_export_segment("mono"))

        self.layout_stereo_export = QtWidgets.QHBoxLayout()
        self.btn_export_L = QtWidgets.QPushButton("EXPORT GAUCHE")
        self.btn_export_R = QtWidgets.QPushButton("EXPORT DROITE")
        style_s = "background-color: #1e8449; color: white; font-weight: bold; padding: 10px;"
        self.btn_export_L.setStyleSheet(style_s)
        self.btn_export_R.setStyleSheet(style_s)
        self.btn_export_L.clicked.connect(lambda: self.on_export_segment("left"))
        self.btn_export_R.clicked.connect(lambda: self.on_export_segment("right"))
        self.layout_stereo_export.addWidget(self.btn_export_L)
        self.layout_stereo_export.addWidget(self.btn_export_R)

        export_vbox.addWidget(self.btn_export_main)
        export_vbox.addLayout(self.layout_stereo_export)
        layout.addWidget(self.group_export)
        layout.addStretch()

        self.lbl_export_status = QtWidgets.QLabel("")
        self.lbl_export_status.setStyleSheet("color: #ecf0f1; font-style: italic;")
        layout.addWidget(self.lbl_export_status)

        self.update_export_buttons_visibility()

    def on_export_segment(self, side="mono"):
        """Lance le VideoSegmentationWorker pour exporter le segment dans segments/."""
        if not self.current_video_path or self.start_ms >= self.end_ms:
            return

        source_path = self.current_video_path
        suffix = ""
        if side == "left" and isinstance(self.current_video_payload, list):
            source_path = self.current_video_payload[0]
            suffix = "_L"
        elif side == "right" and isinstance(self.current_video_payload, list):
            source_path = self.current_video_payload[1]
            suffix = "_R"

        default_name = f"segment_{self.start_ms // 1000}s{suffix}"
        name, ok = QtWidgets.QInputDialog.getText(self.widget, "Export", "Nom du fichier :", text=default_name)

        if ok and name:
            self.last_segment_name = name
            self.group_export.setEnabled(False)
            self.lbl_export_status.setText("Préparation de l'export...")

            segments_dir = os.path.join(os.path.dirname(self.current_video_path), "segments")
            self.segmentation_worker = VideoSegmentationWorker(
                source_path, self.start_ms, self.end_ms, segments_dir
            )
            self.segmentation_worker.progress_updated.connect(self.on_export_progress)
            self.segmentation_worker.export_finished.connect(self.on_segment_finished)
            self.segmentation_worker.export_error.connect(self.on_export_error)
            self.segmentation_worker.start()

    def update_export_buttons_visibility(self):
        """Affiche le bouton mono ou les boutons L/R selon le mode stéréo."""
        is_stereo = getattr(self, 'current_is_stereo', False)
        if hasattr(self, 'btn_export_main'):
            self.btn_export_main.setVisible(not is_stereo)
            self.btn_export_L.setVisible(is_stereo)
            self.btn_export_R.setVisible(is_stereo)

    def on_segment_finished(self, message):
        """Réactive le panneau export et ajoute le segment aux livrables."""
        self.group_export.setEnabled(True)
        # Le worker génère le nom automatiquement — on le retrouve dans le message
        # ou on le reconstruit depuis le chemin réel dans segments/
        segments_dir = os.path.join(os.path.dirname(self.current_video_path), "segments")
        base = os.path.splitext(os.path.basename(self.current_video_path))[0]
        path = os.path.join(segments_dir, f"{base}_segment_{self.start_ms}_{self.end_ms}.mp4")
        self.add_to_deliverables_tree(path)
        self.lbl_export_status.setText("Export terminé.")

    def on_export_progress(self, progress):
        """Met à jour le label de statut avec la progression de l'export."""
        self.lbl_export_status.setText(f"Export en cours : {progress}%")

    def on_export_error(self, err):
        """Réactive l'UI et affiche un message d'erreur critique."""
        self.group_export.setEnabled(True)
        QtWidgets.QMessageBox.critical(self.widget, "Erreur", err)

    def _group_segmentation(self):
        """Construit le groupe de widgets Découpe (timecodes début/fin, boutons)."""
        g = QtWidgets.QGroupBox("Découpe")
        f = QtWidgets.QFormLayout(g)

        self.edit_start_time = QtWidgets.QLineEdit("00:00:00")
        self.edit_end_time = QtWidgets.QLineEdit("00:00:00")
        self.edit_start_time.setInputMask("99:99:99")
        self.edit_end_time.setInputMask("99:99:99")
        self.lbl_segment_duration = QtWidgets.QLabel("Durée: 00:00")

        self.edit_start_time.textChanged.connect(self.on_manual_time_change)
        self.edit_end_time.textChanged.connect(self.on_manual_time_change)

        btn_s = QtWidgets.QPushButton("Début")
        btn_s.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; border-radius: 4px; padding: 5px;"
        )
        btn_s.clicked.connect(self.on_set_start_frame)

        btn_e = QtWidgets.QPushButton("Fin")
        btn_e.setStyleSheet(
            "background-color: #c0392b; color: white; font-weight: bold; border-radius: 4px; padding: 5px;"
        )
        btn_e.clicked.connect(self.on_set_end_frame)

        f.addRow(btn_s, self.edit_start_time)
        f.addRow(btn_e, self.edit_end_time)
        f.addRow(self.lbl_segment_duration)
        return g

    def _group_frame_capture(self):
        """Construit le groupe de widgets Capture (boutons mono/L/R et miniature)."""
        g = QtWidgets.QGroupBox("Capture")
        l = QtWidgets.QVBoxLayout(g)

        self.btn_capture_main = QtWidgets.QPushButton("CAPTURER")
        self.btn_capture_main.clicked.connect(lambda: self.execute_capture("mono"))

        self.layout_stereo_btns = QtWidgets.QHBoxLayout()
        self.btn_capture_L = QtWidgets.QPushButton("GAUCHE")
        self.btn_capture_R = QtWidgets.QPushButton("DROITE")
        self.btn_capture_L.setStyleSheet("background-color: #34495e; color: white;")
        self.btn_capture_R.setStyleSheet("background-color: #34495e; color: white;")
        self.btn_capture_L.clicked.connect(lambda: self.execute_capture("left"))
        self.btn_capture_R.clicked.connect(lambda: self.execute_capture("right"))
        self.layout_stereo_btns.addWidget(self.btn_capture_L)
        self.layout_stereo_btns.addWidget(self.btn_capture_R)

        l.addWidget(self.btn_capture_main)
        l.addLayout(self.layout_stereo_btns)

        self.lbl_thumbnail = QtWidgets.QLabel("Aperçu")
        self.lbl_thumbnail.setFixedSize(160, 90)
        self.lbl_thumbnail.setScaledContents(True)
        self.lbl_thumbnail.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumbnail.setStyleSheet("border: 1px solid #ccc; background: #000;")
        l.addWidget(self.lbl_thumbnail, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        self.btn_capture_L.setVisible(False)
        self.btn_capture_R.setVisible(False)
        return g

    def ms_to_timecode(self, ms):
        """Convertit des millisecondes en chaîne HH:MM:SS."""
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def timecode_to_ms(self, timecode):
        """Convertit une chaîne HH:MM:SS en millisecondes."""
        try:
            parts = timecode.split(':')
            if len(parts) != 3:
                return 0
            h, m, s = map(int, parts)
            return (h * 3600 + m * 60 + s) * 1000
        except ValueError:
            return 0

    def on_manual_time_change(self):
        """Met à jour start_ms/end_ms depuis les champs texte et synchronise les marqueurs timeline."""
        self.start_ms = self.timecode_to_ms(self.edit_start_time.text())
        self.end_ms = self.timecode_to_ms(self.edit_end_time.text())
        duration_s = max(0, (self.end_ms - self.start_ms) // 1000)
        self.lbl_segment_duration.setText(f"Durée: {duration_s // 60:02d}:{duration_s % 60:02d}")
        if hasattr(self.video_player.timeline, 'start_marker_ms'):
            self.video_player.timeline.start_marker_ms = self.start_ms
            self.video_player.timeline.end_marker_ms = self.end_ms
            self.video_player.timeline.update()

    def update_segmentation_display(self):
        """Rafraîchit les champs timecode et la durée affichée depuis start_ms/end_ms."""
        self.edit_start_time.setText(self.ms_to_timecode(self.start_ms))
        self.edit_end_time.setText(self.ms_to_timecode(self.end_ms))
        duration_s = max(0, (self.end_ms - self.start_ms) // 1000)
        self.lbl_segment_duration.setText(f"Durée: {duration_s // 60:02d}:{duration_s % 60:02d}")
        if hasattr(self.video_player.timeline, 'start_marker_ms'):
            self.video_player.timeline.start_marker_ms = self.start_ms
            self.video_player.timeline.end_marker_ms = self.end_ms
            self.video_player.timeline.update()

    def on_timeline_markers_moved(self, start_ms, end_ms):
        """Reçoit les marqueurs déplacés depuis la timeline et met à jour les champs texte."""
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.edit_start_time.blockSignals(True)
        self.edit_end_time.blockSignals(True)
        self.edit_start_time.setText(self.ms_to_timecode(start_ms))
        self.edit_end_time.setText(self.ms_to_timecode(end_ms))
        self.edit_start_time.blockSignals(False)
        self.edit_end_time.blockSignals(False)
        duration_sec = (end_ms - start_ms) // 1000
        if hasattr(self, 'lbl_segment_duration'):
            self.lbl_segment_duration.setText(f"Durée : {duration_sec}s")

    def on_set_start_frame(self):
        """Fixe le marqueur de début à la position courante du player."""
        self.start_ms = self.video_player.player.position()
        self.update_segmentation_display()

    def on_set_end_frame(self):
        """Fixe le marqueur de fin à la position courante du player."""
        self.end_ms = self.video_player.player.position()
        self.update_segmentation_display()

    def execute_capture(self, side="mono"):
        """Extrait la frame courante, ouvre CaptureDialog et sauvegarde si validé."""
        if not self.current_video_path:
            return
        pos = self.video_player.player.position()
        target_path = self.current_video_path
        suffix = ""
        if side == "left" and isinstance(self.current_video_payload, list):
            target_path = self.current_video_payload[0]
            suffix = "_L"
        elif side == "right" and isinstance(self.current_video_payload, list):
            target_path = self.current_video_payload[1]
            suffix = "_R"

        cap = cv2.VideoCapture(target_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, pos)
        ret, frame = cap.read()
        cap.release()

        if ret:
            self.last_raw_frame = frame
            default_name = f"cap_{pos // 1000}s{suffix}"
            is_stereo_ui = (side == "mono" and self.current_is_stereo)
            dialog = CaptureDialog(self.widget.window(), frame, default_name, 0, 10, False, is_stereo=is_stereo_ui)
            if dialog.exec():
                name, final_frame = dialog.get_values()
                if name:
                    self.current_capture_name = name
                    self.current_processed_frame = final_frame
                    self.save_processed_image()
                    self.apply_live_corrections()

    def apply_live_corrections(self):
        """Affiche la dernière frame brute dans la miniature du panneau."""
        if self.last_raw_frame is None:
            return
        rgb = cv2.cvtColor(self.last_raw_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
        self.lbl_thumbnail.setPixmap(QtGui.QPixmap.fromImage(qimg))

    def save_processed_image(self):
        """Écrit la frame traitée dans captures/ et l'ajoute aux livrables."""
        if self.current_processed_frame is None:
            return
        out_dir = os.path.join(os.path.dirname(self.current_video_path), "captures")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{self.current_capture_name}.png")
        cv2.imwrite(path, self.current_processed_frame)
        self.add_to_deliverables_tree(path)

    def add_to_deliverables_tree(self, file_path):
        """Ajoute un fichier livrable (vidéo ou image) avec icône miniature dans l'arbre."""
        if not os.path.exists(file_path):
            return

        if self.deliverables_model.rowCount() > 0:
            first_item = self.deliverables_model.item(0, 0)
            if first_item and "Aucun segment ou capture" in first_item.text():
                self.deliverables_model.clear()
                self.deliverables_model.setHorizontalHeaderLabels(["Nom", "Taille", "Type"])

        file_name = os.path.basename(file_path)
        size_bytes = os.path.getsize(file_path)
        size_str = (f"{size_bytes / (1024*1024):.2f} MB" if size_bytes > 1024 * 1024
                    else f"{size_bytes / 1024:.1f} KB")

        icon = QtGui.QIcon()
        file_type = "Vidéo" if file_path.lower().endswith(('.mp4', '.avi')) else "Image"

        try:
            if file_type == "Image":
                pixmap = QtGui.QPixmap(file_path).scaled(64, 48, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                          QtCore.Qt.TransformationMode.SmoothTransformation)
                icon = QtGui.QIcon(pixmap)
            else:
                cap = cv2.VideoCapture(file_path)
                ret, frame = cap.read()
                if ret:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
                    icon = QtGui.QIcon(QtGui.QPixmap.fromImage(qimg).scaled(64, 48))
                cap.release()
        except Exception as e:
            print(f"Erreur génération icône : {e}")

        item_name = QtGui.QStandardItem(icon, file_name)
        item_name.setData(file_path, QtCore.Qt.ItemDataRole.UserRole)
        self.deliverables_model.appendRow([item_name, QtGui.QStandardItem(size_str), QtGui.QStandardItem(file_type)])

        if self.tree_segment_capture_container:
            self.tree_segment_capture_container.setModel(self.deliverables_model)

    def show_no_campaign_message(self):
        """Affiche un message d'absence de campagne dans l'arbre vidéo."""
        if hasattr(self, 'tree_videos_2') and self.tree_videos_2:
            placeholder = QtGui.QStandardItemModel()
            placeholder.setHorizontalHeaderLabels(["Statut"])
            item = QtGui.QStandardItem("Aucune campagne chargée")
            item.setEditable(False)
            item.setForeground(QtGui.QColor("gray"))
            placeholder.appendRow(item)
            self.tree_videos_2.setModel(placeholder)

    def show_no_cap_seg_message(self):
        """Affiche un message d'absence de livrables dans l'arbre segments/captures."""
        if self.deliverables_model:
            self.deliverables_model.clear()
            self.deliverables_model.setHorizontalHeaderLabels(["Nom", "Taille", "Type"])
            item = QtGui.QStandardItem("Aucun segment ou capture disponible")
            item.setEditable(False)
            item.setForeground(QtGui.QColor("gray"))
            self.deliverables_model.appendRow([item, QtGui.QStandardItem(""), QtGui.QStandardItem("")])
            if self.tree_segment_capture_container:
                self.tree_segment_capture_container.setModel(self.deliverables_model)
