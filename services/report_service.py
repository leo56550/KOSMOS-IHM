"""
Génère un rapport PDF de campagne KOSMOS via matplotlib PdfPages.

Pages :
  1. Couverture — logo, nom campagne, date, stats globales
  2. Résumé — graphe validées / non validées, GPS scatter (si coords)
  3..N. Fiches vidéo — vignette + métadonnées clés (3 par page)
"""

import os
import json
import datetime
import cv2
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

from services.campaign_service import get_video_json_path, get_video_gps_coords
from services.thumbnail_service import _make_thumbnail_icon, THUMB_W, THUMB_H

# ── couleurs KOSMOS ────────────────────────────────────────────────────────────
_BG      = '#0d1b2a'
_PANEL   = '#162433'
_ACCENT  = '#2778A2'
_TEXT    = '#d4e8f5'
_GREEN   = '#4CAF50'
_RED     = '#D94F38'
_GOLD    = '#F2BFB4'
_GREY    = '#5a7a8a'


def _apply_dark_style(fig, axes_list):
    fig.patch.set_facecolor(_BG)
    for ax in axes_list:
        ax.set_facecolor(_PANEL)
        ax.tick_params(colors=_TEXT, labelsize=8)
        ax.xaxis.label.set_color(_TEXT)
        ax.yaxis.label.set_color(_TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(_ACCENT)


def _load_logo_array(logo_path: str, height_px: int = 80) -> np.ndarray | None:
    if not logo_path or not os.path.isfile(logo_path):
        return None
    try:
        img = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        h, w = img.shape[:2]
        scale = height_px / h
        img = cv2.resize(img, (int(w * scale), height_px), interpolation=cv2.INTER_AREA)
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return img.astype(np.float32) / 255.0
    except Exception:
        return None


def _grab_frame_array(video_path: str) -> np.ndarray | None:
    """Extrait la frame du milieu d'une vidéo, renvoie un tableau RGB float32."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total // 2)))
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frame.astype(np.uint8)
    except Exception:
        return None


def _val(data: dict, *keys, default='—') -> str:
    """Navigue récursivement dans un dict JSON et retourne la valeur ou default."""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, {})
    if isinstance(cur, dict):
        v = cur.get('value', None)
    else:
        v = cur
    return str(v) if v not in (None, '', 'null') else default


# ── Page 1 : Couverture ────────────────────────────────────────────────────────

def _page_cover(pdf: PdfPages, campaign_folder: str, logo_arr: np.ndarray | None,
                n_total: int, n_valid: int, total_sec: float):
    fig = plt.figure(figsize=(11.69, 8.27))   # A4 paysage
    fig.patch.set_facecolor(_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor(_BG)

    # Logo
    if logo_arr is not None:
        logo_big = _load_logo_array(
            os.path.join(os.path.dirname(__file__), '..', 'img', 'logo_kosmos.png'),
            height_px=120
        )
        if logo_big is not None:
            im = OffsetImage(logo_big, zoom=1.0)
            ab = AnnotationBbox(im, (0.5, 0.82), xycoords='axes fraction',
                                frameon=False, box_alignment=(0.5, 0.5))
            ax.add_artist(ab)

    name = os.path.basename(campaign_folder.rstrip('/\\'))
    ax.text(0.5, 0.65, f"Campagne : {name}", ha='center', va='center',
            color=_GOLD, fontsize=22, fontweight='bold',
            transform=ax.transAxes, fontfamily='Segoe UI')

    ax.text(0.5, 0.56, f"Rapport généré le {datetime.date.today().strftime('%d/%m/%Y')}",
            ha='center', va='center', color=_GREY, fontsize=11,
            transform=ax.transAxes)

    # Stats band
    pct = int(n_valid / n_total * 100) if n_total else 0
    color_pct = _GREEN if pct == 100 else (_ACCENT if pct > 0 else _GREY)
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = int(total_sec % 60)
    dur_str = f"{h}h {m:02d}min {s:02d}s" if h else f"{m}min {s:02d}s"

    stats = [
        ("Vidéos", str(n_total)),
        ("Durée totale", dur_str),
        ("Validées", f"{n_valid}/{n_total}  ({pct}%)", color_pct),
    ]
    xs = [0.25, 0.50, 0.75]
    for (label, value, *color_opt), x in zip(stats, xs):
        c = color_opt[0] if color_opt else _TEXT
        ax.text(x, 0.42, label, ha='center', va='center', color=_GREY,
                fontsize=10, transform=ax.transAxes)
        ax.text(x, 0.36, value, ha='center', va='center', color=c,
                fontsize=16, fontweight='bold', transform=ax.transAxes)

    # Bottom stripe
    ax.plot([0, 1], [0.08, 0.08], color=_ACCENT, linewidth=1,
            transform=ax.transAxes, zorder=10)
    ax.text(0.5, 0.04, "KOSMOS IHM — Institut Mines-Télécom Atlantique",
            ha='center', va='center', color=_GREY, fontsize=9,
            transform=ax.transAxes)

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Page 2 : Résumé graphique ──────────────────────────────────────────────────

def _page_summary(pdf: PdfPages, video_entries: list, gps_coords: list):
    """video_entries: list of dicts with keys name, valid(bool), duration_s"""
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor(_BG)

    has_gps = len(gps_coords) > 0
    if has_gps:
        gs = gridspec.GridSpec(1, 2, figure=fig, left=0.08, right=0.95,
                               top=0.88, bottom=0.12, wspace=0.35)
        ax_bar = fig.add_subplot(gs[0, 0])
        ax_gps = fig.add_subplot(gs[0, 1])
    else:
        ax_bar = fig.add_axes([0.12, 0.15, 0.76, 0.68])
        ax_gps = None

    _apply_dark_style(fig, [ax_bar] + ([ax_gps] if ax_gps else []))

    # Bar chart
    n_valid = sum(1 for e in video_entries if e['valid'])
    n_invalid = len(video_entries) - n_valid
    bars = ax_bar.bar(['Validées', 'Non validées'], [n_valid, n_invalid],
                      color=[_GREEN, _RED], width=0.5, edgecolor=_BG, linewidth=1.5)
    for bar, val in zip(bars, [n_valid, n_invalid]):
        ax_bar.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                    str(val), ha='center', va='bottom', color=_TEXT, fontsize=12, fontweight='bold')
    ax_bar.set_ylabel("Nombre de vidéos", color=_TEXT, fontsize=10)
    ax_bar.set_title("Statut de validation", color=_GOLD, fontsize=13, fontweight='bold', pad=10)
    ax_bar.set_ylim(0, max(n_valid, n_invalid, 1) * 1.25)

    # GPS scatter
    if ax_gps and gps_coords:
        lats = [c[0] for c in gps_coords]
        lons = [c[1] for c in gps_coords]
        ax_gps.scatter(lons, lats, c=_ACCENT, s=40, alpha=0.8, edgecolors=_TEXT, linewidths=0.5)
        ax_gps.set_xlabel("Longitude", color=_TEXT, fontsize=9)
        ax_gps.set_ylabel("Latitude", color=_TEXT, fontsize=9)
        ax_gps.set_title("Positions GPS", color=_GOLD, fontsize=13, fontweight='bold', pad=10)
        ax_gps.tick_params(labelsize=7)

    fig.suptitle("Résumé de campagne", color=_TEXT, fontsize=15, fontweight='bold', y=0.97)

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Pages 3+ : Fiches vidéo (3 par page) ──────────────────────────────────────

def _page_video_cards(pdf: PdfPages, entries: list):
    """entries: list of dicts {name, path, valid, data(json dict)}"""
    CARDS_PER_PAGE = 3
    for page_start in range(0, len(entries), CARDS_PER_PAGE):
        batch = entries[page_start:page_start + CARDS_PER_PAGE]
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.patch.set_facecolor(_BG)

        n = len(batch)
        gs = gridspec.GridSpec(n, 2, figure=fig,
                               left=0.03, right=0.97, top=0.92, bottom=0.06,
                               wspace=0.25, hspace=0.55,
                               width_ratios=[1, 2.5])

        fig.suptitle("Fiches vidéo", color=_TEXT, fontsize=13, fontweight='bold', y=0.97)

        for i, entry in enumerate(batch):
            ax_thumb = fig.add_subplot(gs[i, 0])
            ax_meta  = fig.add_subplot(gs[i, 1])

            ax_thumb.set_facecolor(_PANEL)
            ax_meta.set_facecolor(_PANEL)
            for ax in (ax_thumb, ax_meta):
                for spine in ax.spines.values():
                    spine.set_edgecolor(_ACCENT)
                ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

            # Thumbnail
            frame = _grab_frame_array(entry['path'])
            if frame is not None:
                ax_thumb.imshow(frame, aspect='auto')
            else:
                ax_thumb.text(0.5, 0.5, 'N/A', ha='center', va='center',
                              color=_GREY, transform=ax_thumb.transAxes, fontsize=10)
            ax_thumb.set_title(entry['name'], color=_GOLD, fontsize=8,
                               fontweight='bold', pad=3, loc='left')

            # Metadata
            ax_meta.set_xlim(0, 1)
            ax_meta.set_ylim(0, 1)
            d = entry.get('data') or {}

            status_color = _GREEN if entry['valid'] else _RED
            status_text  = 'Validée' if entry['valid'] else 'Non validée'
            ax_meta.text(0.98, 0.92, status_text, ha='right', va='top',
                         color=status_color, fontsize=8, fontweight='bold',
                         transform=ax_meta.transAxes)

            fields = [
                ("Durée",      _val(d, 'video_observation', 'duration', 'value')),
                ("GPS",        _val(d, 'video_observation', 'gps_position', 'value')),
                ("Prof. max",  _val(d, 'video_observation', 'max_depth', 'value')),
                ("Site",       _val(d, 'survey', 'site', 'value')),
                ("Protection", _val(d, 'survey', 'protectionStatus1', 'value')),
                ("Caméra",     _val(d, 'system', 'camera', 'value')),
                ("Exploitable",_val(d, 'video_observation', 'exploitable', 'value')),
            ]

            y_start = 0.82
            dy = 0.14
            for label, value in fields:
                ax_meta.text(0.01, y_start, f"{label} :", ha='left', va='top',
                             color=_GREY, fontsize=7.5, transform=ax_meta.transAxes)
                ax_meta.text(0.30, y_start, value, ha='left', va='top',
                             color=_TEXT, fontsize=7.5, transform=ax_meta.transAxes)
                y_start -= dy

        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)


# ── Point d'entrée public ──────────────────────────────────────────────────────

def generate_pdf_report(campaign_folder: str, video_paths: list[str],
                        output_path: str, logo_path: str | None = None) -> str:
    """
    Génère le rapport PDF.

    Args:
        campaign_folder: Dossier racine de la campagne.
        video_paths: Liste ordonnée des chemins MP4 (hors corbeille).
        output_path: Chemin de sortie du PDF.
        logo_path: Chemin du logo PNG KOSMOS (optionnel).

    Returns:
        output_path si succès, message d'erreur sinon.
    """
    # Collect per-video data
    entries = []
    gps_coords = []
    total_sec = 0.0

    for path in video_paths:
        name = os.path.basename(path)
        json_path = get_video_json_path(path)
        data = {}
        valid = False
        if os.path.isfile(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                expl = data.get('video_observation', {}).get('exploitable', {}).get('value')
                valid = bool(expl and str(expl).strip())
            except Exception:
                pass

        # Duration from video file
        try:
            cap = cv2.VideoCapture(path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            cap.release()
            total_sec += frames / fps
        except Exception:
            pass

        # GPS
        coords = get_video_gps_coords(path)
        if coords:
            gps_coords.append(coords)

        entries.append({'name': name, 'path': path, 'valid': valid, 'data': data})

    n_total = len(entries)
    n_valid = sum(1 for e in entries if e['valid'])

    logo_arr = _load_logo_array(logo_path) if logo_path else None

    try:
        with PdfPages(output_path) as pdf:
            _page_cover(pdf, campaign_folder, logo_arr, n_total, n_valid, total_sec)
            _page_summary(pdf, entries, gps_coords)
            if entries:
                _page_video_cards(pdf, entries)

            # PDF metadata
            d = pdf.infodict()
            d['Title'] = f"Rapport KOSMOS — {os.path.basename(campaign_folder)}"
            d['Author'] = 'KOSMOS IHM'
            d['CreationDate'] = datetime.datetime.now()

        return output_path
    except Exception as e:
        return f"Erreur génération PDF : {e}"
