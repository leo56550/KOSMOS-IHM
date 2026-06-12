from PyQt6 import QtWidgets


class ValidationView:
    """Vue de la page Validation."""

    def __init__(self, widget: QtWidgets.QWidget):
        self.widget = widget

        self.tree_videos = widget.findChild(QtWidgets.QTreeView, "tree_videos_valid")
        self.lecteur_container = widget.findChild(QtWidgets.QFrame, "lecteur_timeline_container")
        self.combo_exploitable = widget.findChild(QtWidgets.QComboBox, "combo_exploitable")
        self.lbl_video_name = widget.findChild(QtWidgets.QLabel, "lbl_video_name_valid")
