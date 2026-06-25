import os

from PyQt6 import QtCore, QtWidgets

_NOTES_FILENAME = "session_notes.txt"

_STYLE = """
QDialog {
    background-color: #0d1b2a;
}
QPlainTextEdit {
    background-color: #162433;
    color: #d4e8f5;
    border: 1px solid #2a4057;
    border-radius: 4px;
    padding: 8px;
    font-family: 'Segoe UI', 'Consolas', sans-serif;
    font-size: 13px;
    selection-background-color: #2778A2;
}
QLabel {
    color: #7ec8e3;
    font-size: 11px;
    font-family: 'Segoe UI', sans-serif;
}
QPushButton {
    background-color: #1e3448;
    color: #d4e8f5;
    border: 1px solid #2a4057;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
    font-family: 'Segoe UI', sans-serif;
}
QPushButton:hover {
    background-color: #2778A2;
    border-color: #2778A2;
}
"""


class NotesDialog(QtWidgets.QDialog):
    """Bloc-notes libre associé à la campagne, auto-sauvegardé dans session_notes.txt."""

    def __init__(self, campaign_folder: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self._campaign_folder = campaign_folder
        self._notes_path = os.path.join(campaign_folder, _NOTES_FILENAME)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Notes de session")
        self.resize(600, 420)
        self.setStyleSheet(_STYLE)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(8)

        self._label = QtWidgets.QLabel(f"Campagne : {os.path.basename(campaign_folder)}")
        layout.addWidget(self._label)

        self._editor = QtWidgets.QPlainTextEdit()
        self._editor.setPlaceholderText("Saisir vos notes ici…")
        layout.addWidget(self._editor, stretch=1)

        self._status = QtWidgets.QLabel("")
        self._status.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._status)

        btn_close = QtWidgets.QPushButton("Fermer")
        btn_close.clicked.connect(self.close)
        btn_bar = QtWidgets.QHBoxLayout()
        btn_bar.addStretch()
        btn_bar.addWidget(btn_close)
        layout.addLayout(btn_bar)

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1500)
        self._save_timer.timeout.connect(self._save)

        self._editor.textChanged.connect(self._on_text_changed)

        self._load()

    def _load(self):
        if os.path.isfile(self._notes_path):
            try:
                with open(self._notes_path, 'r', encoding='utf-8') as f:
                    self._editor.setPlainText(f.read())
            except Exception:
                pass
        self._status.setText("")

    def _on_text_changed(self):
        self._status.setText("Non sauvegardé…")
        self._save_timer.start()

    def _save(self):
        try:
            with open(self._notes_path, 'w', encoding='utf-8') as f:
                f.write(self._editor.toPlainText())
            self._status.setText("Sauvegardé")
        except Exception as e:
            self._status.setText(f"Erreur : {e}")

    def closeEvent(self, event):
        self._save_timer.stop()
        self._save()
        super().closeEvent(event)
