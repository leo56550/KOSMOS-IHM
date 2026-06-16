from PyQt6 import QtWidgets


class ExtractionView:
    """Vue de la page Extraction."""

    def __init__(self, widget: QtWidgets.QWidget):
        """Expose les widgets de la page Extraction (conteneur paramètres, lecteur, arbre vidéos)."""
        self.widget = widget

        children = {w.objectName(): w for w in widget.findChildren(QtWidgets.QWidget)}

        self.param_container = children.get("param_container")
        self.lecteur_container = children.get("lecteur_timeline_container_2")
        self.tree_videos = children.get("tree_videos_2")
        self.tree_deliverables = children.get("tree_segment_capture_container")
