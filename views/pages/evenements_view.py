from PyQt6 import QtWidgets


class EvenementsView:
    """Vue de la page Événements."""

    def __init__(self, widget: QtWidgets.QWidget):
        self.widget = widget

        # TreeView des vidéos (liste filtrée)
        self.tree_videos = widget.findChild(QtWidgets.QTreeView, "tree_videos_event")

        # TreeView des événements
        self.tree_events = widget.findChild(QtWidgets.QTreeView, "treeView_events")

        # Conteneur du lecteur+timeline
        self.lecteur_container = widget.findChild(QtWidgets.QFrame, "lecteur_timeline_container_event")

        # Boutons événements
        self.btn_capturer = widget.findChild(QtWidgets.QPushButton, "btn_capturer")
        self.btn_finir = widget.findChild(QtWidgets.QPushButton, "btn_finir")
        self.btn_supprimer = widget.findChild(QtWidgets.QPushButton, "btn_supprimer_event")
        self.btn_export_csv = widget.findChild(QtWidgets.QPushButton, "btn_export_csv")
        self.btn_export_images = widget.findChild(QtWidgets.QPushButton, "btn_export_images")

        # Sélecteurs de catégorie et type d'événement
        self.combo_category = widget.findChild(QtWidgets.QComboBox, "combo_categorie")
        self.combo_event_type = widget.findChild(QtWidgets.QComboBox, "combo_type_event")
        self.edit_event_label = widget.findChild(QtWidgets.QLineEdit, "edit_label_event")

        # Statut d'enregistrement
        self.lbl_recording_status = widget.findChild(QtWidgets.QLabel, "lbl_recording_status")
