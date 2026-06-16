from PyQt6 import QtWidgets


class MetadonneesView:
    """Vue de la page Métadonnées."""

    def __init__(self, widget: QtWidgets.QWidget):
        """Expose les widgets de la page Métadonnées (arbre, conteneurs système/campagne/météo/vidéo)."""
        self.widget = widget

        self.tree_videos = widget.findChild(QtWidgets.QTreeView, "tree_videos")
        self.graph_trash_container = widget.findChild(QtWidgets.QFrame, "graph_trash_container")
        self.container_weather_data = widget.findChild(QtWidgets.QFrame, "container_meteo_data")
        self.data_system_container = widget.findChild(QtWidgets.QFrame, "data_system_container")
        self.data_survey_container = widget.findChild(QtWidgets.QFrame, "data_survey_container")
        self.specific_container_data = widget.findChild(QtWidgets.QFrame, "specific_container_data")
