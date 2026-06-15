from PyQt6 import QtCore, QtWidgets


class QualifView:
    """Vue de la page Qualification.

    Trouve et expose tous les widgets UI, et crée les sous-layouts nécessaires.
    """

    def __init__(self, widget: QtWidgets.QWidget):
        self.widget = widget

        # --- Arbres de vidéos ---
        self.video_tree = widget.findChild(QtWidgets.QTreeView, "video_tree")
        self.trash_video_tree = widget.findChild(QtWidgets.QTreeView, "trash_video_tree")

        # --- Conteneurs ---
        self.frame_campaign = widget.findChild(QtWidgets.QFrame, "frame_campagne")
        self.mini_map_container = widget.findChild(QtWidgets.QFrame, "mini_map_container")
        self.frame_miniature = widget.findChild(QtWidgets.QFrame, "frame_miniature")

        # --- Zone de propriétés de campagne (scroll + formulaire dynamique) ---
        self.dynamic_form_container = None
        self.scroll_campaign = None
        self.lbl_section_title = None
        self._setup_campaign_form()

        # --- Zone de miniatures de rotation ---
        self.scroll_layout = None
        self._setup_miniature_area()

    def _setup_campaign_form(self):
        if not self.frame_campaign:
            return
        layout = QtWidgets.QVBoxLayout(self.frame_campaign)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        self.lbl_section_title = QtWidgets.QLabel("Campaign Properties")
        self.lbl_section_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #F2BFB4;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 5px;"
        )
        self.lbl_section_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_section_title)

        self.scroll_campaign = QtWidgets.QScrollArea(self.frame_campaign)
        self.scroll_campaign.setWidgetResizable(True)
        self.scroll_campaign.setStyleSheet("background: transparent; border: none;")

        self.dynamic_form_container = QtWidgets.QWidget()
        self.scroll_campaign.setWidget(self.dynamic_form_container)
        layout.addWidget(self.scroll_campaign)

    def _setup_miniature_area(self):
        if not self.frame_miniature:
            return
        if self.frame_miniature.layout():
            old = self.frame_miniature.layout()
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(old)

        scroll_area = QtWidgets.QScrollArea(self.frame_miniature)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: #2778a2; border: none;")

        scroll_content = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)

        main_layout = QtWidgets.QVBoxLayout(self.frame_miniature)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)

    def setup_video_tree_header(self, video_model, trash_model):
        """Configure les QTreeViews avec leurs modèles et titres."""
        if self.video_tree:
            self.video_tree.setModel(video_model)
            splitter = self.video_tree.parentWidget()
            container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            self.lbl_videos_title = QtWidgets.QLabel("Campaign Videos")
            self.lbl_videos_title.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #F2BFB4;"
                " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 2px;"
            )
            self.lbl_videos_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            if hasattr(splitter, "indexOf"):
                idx = splitter.indexOf(self.video_tree)
                layout.addWidget(self.lbl_videos_title)
                layout.addWidget(self.video_tree)
                splitter.insertWidget(idx, container)
            for i in range(video_model.columnCount()):
                self.video_tree.resizeColumnToContents(i)
            self.video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        if self.trash_video_tree:
            self.trash_video_tree.setModel(trash_model)
            splitter_trash = self.trash_video_tree.parentWidget()
            container_trash = QtWidgets.QWidget()
            layout_trash = QtWidgets.QVBoxLayout(container_trash)
            layout_trash.setContentsMargins(0, 0, 0, 0)
            layout_trash.setSpacing(5)
            self.lbl_trash_title = QtWidgets.QLabel("Removed Videos")
            self.lbl_trash_title.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #D94F38;"
                " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 2px;"
            )
            self.lbl_trash_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            if hasattr(splitter_trash, "indexOf"):
                idx_t = splitter_trash.indexOf(self.trash_video_tree)
                layout_trash.addWidget(self.lbl_trash_title)
                layout_trash.addWidget(self.trash_video_tree)
                splitter_trash.insertWidget(idx_t, container_trash)
            for i in range(trash_model.columnCount()):
                self.trash_video_tree.resizeColumnToContents(i)
            self.trash_video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.trash_video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
