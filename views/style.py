"""
KOSMOS Design System — charte graphique v02/10/2025

Couleurs officielles :
  #20415D  Indigo dye  (fond sombre, toolbar, boutons principaux)
  #2778A2  Cerulean    (accentuation, bordures, bouton actif)
  #D94F38  Jasper      (alertes, suppression, danger)
  #F2BFB4  Melon       (texte champs, surbrillance douce)

Polices officielles :
  Titre : Montserrat Bold → fallback Segoe UI Black / Segoe UI SemiBold
  Corps : Roboto / Noto Sans → fallback Segoe UI
"""

# ── Palette ───────────────────────────────────────────────────────────────
C_INDIGO   = "#20415D"   # Indigo dye  — fond toolbar / boutons
C_CERULEAN = "#2778A2"   # Cerulean    — accent / bordures
C_JASPER   = "#D94F38"   # Jasper      — danger / suppression / trash
C_MELON    = "#F2BFB4"   # Melon       — texte champs / highlight doux

# Dérivés fonctionnels
C_BG_DARK    = "#111820"   # Fond fenêtre principale (bleu-noir)
C_BG_SURFACE = "#1b2c3d"   # Fond panneaux / frames
C_BG_INPUT   = "#162433"   # Fond champs de saisie
C_HOVER      = "#3290c2"   # État hover (entre Cerulean et clair)
C_PRESSED    = "#152d42"   # État pressed
C_BORDER     = "#2778A2"   # Bordure principale
C_BORDER_SUB = "#2a4057"   # Bordure subtile
C_TEXT       = "#ffffff"   # Texte principal
C_TEXT_DIM   = "#b0c8d8"   # Texte secondaire (gris-bleu)
C_TEXT_FIELD = "#F2BFB4"   # Valeur dans champs (Melon)

# ── Polices ────────────────────────────────────────────────────────────────
FONT_TITLE   = '"Montserrat", "Segoe UI Black", "Segoe UI", sans-serif'
FONT_SUBTITLE = '"Grand Hotel", "Segoe UI", cursive'
FONT_BODY    = '"Roboto", "Noto Sans", "Segoe UI", sans-serif'

# ── QSS réutilisables ─────────────────────────────────────────────────────

# Bouton principal (indigo → cerulean hover)
BTN_PRIMARY = f"""
    QPushButton {{
        background-color: {C_INDIGO}; color: {C_TEXT}; font-weight: bold;
        border: 1px solid {C_CERULEAN}; border-radius: 4px;
        padding: 6px 14px; font-size: 12px; font-family: {FONT_BODY};
    }}
    QPushButton:hover {{ background-color: {C_CERULEAN}; }}
    QPushButton:pressed {{ background-color: {C_PRESSED}; border-color: {C_TEXT}; }}
    QPushButton:disabled {{ color: #555; background-color: #1a1a1a; border-color: #333; }}
"""

# Bouton danger (jasper)
BTN_DANGER = f"""
    QPushButton {{
        background-color: {C_INDIGO}; color: {C_JASPER}; font-weight: bold;
        border: 1px solid {C_JASPER}; border-radius: 4px;
        padding: 6px 14px; font-size: 12px;
    }}
    QPushButton:hover {{ background-color: {C_JASPER}; color: white; }}
    QPushButton:pressed {{ background-color: #a83020; color: white; }}
"""

# Bouton toggle (checkable)
BTN_TOGGLE = f"""
    QPushButton {{
        background-color: {C_INDIGO}; color: {C_TEXT}; font-weight: bold;
        border: 1px solid {C_BORDER_SUB}; border-radius: 4px; padding: 4px 10px;
    }}
    QPushButton:checked {{ background-color: {C_CERULEAN}; border-color: {C_CERULEAN}; }}
    QPushButton:hover:!disabled {{ background-color: {C_CERULEAN}; }}
    QPushButton:disabled {{ color: #555; background-color: #1a1a1a; border-color: #333; }}
"""

# Champ de saisie
FIELD = f"""
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {C_BG_INPUT}; color: {C_TEXT_FIELD};
        border: 1px solid {C_BORDER_SUB}; border-radius: 3px; padding: 3px 6px;
        font-family: {FONT_BODY}; font-size: 11px;
    }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
        border-color: {C_CERULEAN};
    }}
"""

# ComboBox
COMBO = f"""
    QComboBox {{
        background-color: {C_BG_INPUT}; color: {C_TEXT_FIELD};
        border: 1px solid {C_BORDER_SUB}; border-radius: 3px; padding: 2px 6px;
    }}
    QComboBox:hover {{ border-color: {C_CERULEAN}; }}
    QComboBox QAbstractItemView {{
        background-color: {C_BG_SURFACE}; color: {C_TEXT};
        selection-background-color: {C_CERULEAN};
    }}
"""

# GroupBox
GROUPBOX = f"""
    QGroupBox {{
        border: 1px solid {C_CERULEAN}; border-radius: 5px;
        margin-top: 18px; padding-top: 10px; color: {C_TEXT};
        font-family: {FONT_BODY}; font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; subcontrol-position: top left;
        padding: 3px 8px; background-color: {C_CERULEAN}; color: {C_TEXT};
        border-radius: 3px; font-size: 12px;
    }}
"""

# Slider
SLIDER = f"""
    QSlider::groove:horizontal {{ height: 4px; background: {C_BORDER_SUB}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {C_CERULEAN}; width: 12px; height: 12px;
        margin: -4px 0; border-radius: 6px;
    }}
    QSlider::sub-page:horizontal {{ background: {C_CERULEAN}; border-radius: 2px; }}
"""

# ScrollArea
SCROLL_AREA = f"""
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 6px; background: transparent; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {C_CERULEAN}; border-radius: 3px; min-height: 20px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

# QTreeView
TREE_VIEW = f"""
    QTreeView {{
        background-color: {C_BG_SURFACE}; color: {C_TEXT};
        border: 1px solid {C_BORDER_SUB}; alternate-background-color: {C_BG_DARK};
        font-family: {FONT_BODY}; font-size: 11px;
    }}
    QTreeView::item:selected {{ background-color: {C_CERULEAN}; color: white; }}
    QTreeView::item:hover {{ background-color: {C_INDIGO}; }}
    QHeaderView::section {{
        background-color: {C_INDIGO}; color: {C_MELON};
        padding: 4px 8px; border: none; font-weight: bold;
        font-family: {FONT_BODY}; font-size: 11px;
    }}
"""

# Label titre de section
SECTION_TITLE = f"color: {C_MELON}; font-size: 13px; font-weight: bold; font-family: {FONT_TITLE};"
SECTION_LINE  = f"border-bottom: 1px solid {C_CERULEAN}; margin-bottom: 4px;"

# Label standard
LABEL         = f"color: {C_TEXT_DIM}; font-family: {FONT_BODY}; font-size: 11px; border: none; min-width: 130px;"

# ── Application global stylesheet ─────────────────────────────────────────
APP_STYLESHEET = f"""
QMainWindow, QDialog, QWidget {{
    background-color: {C_BG_DARK};
    color: {C_TEXT};
    font-family: {FONT_BODY};
    font-size: 11px;
}}
QToolTip {{
    background-color: {C_INDIGO}; color: {C_TEXT};
    border: 1px solid {C_CERULEAN}; padding: 4px;
    font-family: {FONT_BODY};
}}
QSplitter::handle {{
    background-color: {C_BORDER_SUB};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}
QCheckBox {{ color: {C_TEXT}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C_CERULEAN}; border-radius: 3px;
    background-color: {C_BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {C_CERULEAN};
}}
QLabel {{ color: {C_TEXT}; }}
QMessageBox {{ background-color: {C_INDIGO}; color: {C_TEXT}; }}
QMessageBox QPushButton {{
    background-color: {C_CERULEAN}; color: {C_TEXT}; font-weight: bold;
    border-radius: 4px; padding: 5px 14px; min-width: 60px;
}}
{SCROLL_AREA}
"""

# ── Helpers ───────────────────────────────────────────────────────────────

def section_header_label(text: str, color: str = C_MELON) -> str:
    """Retourne le texte QLabel pour un titre de section."""
    return text

def title_style(size: int = 13, color: str = C_MELON) -> str:
    return f"color: {color}; font-size: {size}px; font-weight: bold; font-family: {FONT_TITLE};"

def label_style(color: str = C_TEXT_DIM, size: int = 11) -> str:
    return f"color: {color}; font-size: {size}px; font-family: {FONT_BODY}; border: none;"

def badge_style(color: str = C_CERULEAN) -> str:
    return (f"color: white; background-color: {color}; border-radius: 3px; "
            f"padding: 1px 5px; font-size: 10px; font-weight: bold;")
