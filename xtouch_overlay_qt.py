#!/usr/bin/env python3
"""Indication « SEND ON FADER » à l'écran du PC, en Qt, au style de X/M32 Gain Recall v3 (demande de Joseph, 15/10).

Processus séparé (Qt veut son propre fil principal), piloté par le pont via stdin, une ligne JSON par changement :
    {"text": "FX 1", "sub": "Reverb", "color": "#7f77dd"}     (mode sends)   |   {"text": null}   (mode normal)
    {"quit": true}
Bandeau au centre de la LV1 pendant BANNER_MS (fondu), puis cadre rouge autour de la LV1 qui respire doucement, avec
une étiquette en bas au centre. Fenêtres sans cadre, toujours devant, sans focus, TRAVERSÉES PAR LES CLICS
(Qt.WindowTransparentForInput) : jamais de geste perdu sur l'écran tactile de la LV1.

Style repris de x32_qt_float (v3) : fond #111213, contour #3a3e43, texte #e9edf0 / #8c939a, Segoe UI gras,
rectangles arrondis, rouge 48 V en dégradé (255,120,105) -> (225,22,32), fondu 260 ms.

    py xtouch_overlay_qt.py --demo      # démo 10 s
    py xtouch_overlay_qt.py --reglage   # réglage à la main des blocs du rappel de pistes (Extender, X-Touch, master)
    py xtouch_overlay_qt.py --taille petit|grand   # bascule entre les deux hauteurs mémorisées (sans argument : l'autre)
"""
import json
import math
import os
import sys
import threading
import time

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")     # pixels = pixels écran (comme x32-gain-recall v3)

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from lv1 import layout as L
from lv1 import screen
from lv1.layout import UK_PITCH, KEY_L, KEY_T, KEY_W, KEY_H, KEY_R, TOAST_RIGHT, TOAST_BOTTOM, BTN_RECT

PANEL, LINE2, TXT, MUT = "#111213", "#3a3e43", "#e9edf0", "#8c939a"
RED_TOP, RED_BOT = QColor(255, 120, 105), QColor(225, 22, 32)
FADE_MS = 260
BANNER_MS = 2500
BREATH_S = 2.4                      # période de la respiration du cadre
FRAME_MIN, FRAME_MAX = 0.35, 0.95
BORDER = 5
# Notification de couche : taille (px), visible TOAST_MS puis fondu ; son coin bas-droit (TOAST_RIGHT,
# TOAST_BOTTOM) est une position de l'écran LV1 : lv1/layout.py.
TOAST_W, TOAST_H, TOAST_MS = 260, 64, 2500
FLAGS = (Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
         | Qt.WindowTransparentForInput)


def lv1_rect(mixer=1):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import lv1_clic
        t = lv1_clic.Target(mixer)
        return t.rect if t.hwnd and not lv1_clic.u32().IsIconic(t.hwnd) else None
    except Exception:
        return None


def foreground_pid():
    """Processus de la fenêtre au premier plan (0 si inconnu)."""
    try:
        return screen.foreground_pid()
    except Exception:
        return 0


def lv1_pid(mixer=1):
    try:
        h, _ = screen.lv1_window(mixer)
        return screen.window_pid(h) if h else None
    except Exception:
        return None


def red_gradient(r):
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, RED_TOP)
    g.setColorAt(1, RED_BOT)
    return g


class Banner(QWidget):
    """Carte sombre arrondie : pastille rouge « SEND ON FADER », liseré à la couleur de l'aux, nom + piste."""

    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text, self.sub, self.color = "", "", None
        self.f_pill = QFont("Segoe UI", 11, QFont.Bold)
        self.f_name = QFont("Segoe UI", 28, QFont.Bold)
        self.f_sub = QFont("Segoe UI", 13, QFont.Bold)
        self.resize(560, 150)

    def set(self, text, sub, color):
        self.text, self.sub, self.color = text, sub or "", color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(PANEL))
        p.setPen(QPen(QColor(LINE2), 1.2))
        p.drawPath(path)
        # liseré du haut à la couleur de la piste Fx / Mon (comme la pastille de colonne du float v3)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 6), QColor(self.color or LINE2))
        p.restore()
        pill = QRectF(r.left() + 24, r.top() + 24, 150, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(red_gradient(pill))
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor("#ffffff"))
        p.setFont(self.f_pill)
        p.drawText(pill, Qt.AlignCenter, "SEND ON FADER")
        p.setPen(QColor(TXT))
        p.setFont(self.f_name)
        p.drawText(QRectF(r.left() + 24, r.top() + 58, r.width() - 48, 50), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        if self.sub:
            p.setPen(QColor(MUT))
            p.setFont(self.f_sub)
            p.drawText(QRectF(r.left() + 24, r.top() + 106, r.width() - 48, 26), Qt.AlignLeft | Qt.AlignVCenter,
                       self.sub)


class LayerToast(QWidget):
    """Couche affichée, en bas à droite de la LV1 comme une notification (demande de Joseph du 16/10) : petite carte
    sombre, liseré bleu LV1, le NOM de la couche seul (Ch 17-32, Grp/Fx, Page-1… : « juste le nom du layer »).
    Traversée par les clics."""

    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.name, self.sub = "", ""
        self.f_lbl = QFont("Segoe UI", 10, QFont.Bold)
        self.f_name = QFont("Segoe UI", 22, QFont.Bold)
        self.resize(TOAST_W, TOAST_H)

    def set(self, name, sub):
        self.name, self.sub = name, sub or ""
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(PANEL))
        p.setPen(QPen(QColor(LINE2), 1.2))
        p.drawPath(path)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), 6, r.height()), A_BLUE)          # liseré gauche : bleu des boutons LV1
        p.restore()
        p.setPen(QColor(TXT))
        p.setFont(self.f_name)
        p.drawText(QRectF(r.left() + 20, r.top(), r.width() - 32, r.height()), Qt.AlignLeft | Qt.AlignVCenter, self.name)


class Frame(QWidget):
    """Cadre rouge arrondi autour de la LV1 + étiquette en bas au centre ; l'intérieur reste transparent."""

    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text, self.color = "", None
        self.f_tag = QFont("Segoe UI", 10, QFont.Bold)

    def set(self, text, color):
        self.text, self.color = text, color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(BORDER / 2, BORDER / 2, -BORDER / 2, -BORDER / 2)
        pen = QPen(RED_BOT, BORDER)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)
        tw = 26 + 9 * len(self.text) + 120
        tag = QRectF((self.width() - tw) / 2, self.height() - BORDER - 30, tw, 26)
        p.setPen(QPen(QColor(LINE2), 1))
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(tag, 8, 8)
        pill = QRectF(tag.left() + 4, tag.top() + 4, 112, tag.height() - 8)
        p.setPen(Qt.NoPen)
        p.setBrush(red_gradient(pill))
        p.drawRoundedRect(pill, 5, 5)
        p.setPen(QColor("#ffffff"))
        p.setFont(self.f_tag)
        p.drawText(pill, Qt.AlignCenter, "SEND ON FADER")
        if self.color:
            p.setBrush(QColor(self.color))
            p.drawEllipse(QRectF(pill.right() + 8, tag.center().y() - 4, 8, 8))
        p.setPen(QColor(TXT))
        p.drawText(QRectF(pill.right() + 20, tag.top(), tag.width() - pill.width() - 24, tag.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, self.text)


# Pastille A/B posée sur la User Key « FlipAB » de la LV1 (demande de Joseph, 15/10 : voir à tout moment si les
# entrées sont sur A ou B). Position et couleurs de la touche d'origine : lv1/layout.py. La pastille la recopie en
# débordant de PAD px : rien ne transparaît.
PAD = 2
ROW_BG, KEY_BG, KEY_LINE = QColor(*L.ROW_BG), QColor(*L.KEY_BG), QColor(*L.KEY_LINE)
A_BLUE = QColor(*L.A_BLUE)             # bouton A/B actif de la LV1


class AbBadge(QWidget):
    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.ab = "A"
        self.alert = False               # diagonale B cassée : contour rouge + « ! » (Joseph, 16/10 : la barre du haut
        self.f = QFont("Segoe UI", 11, QFont.Bold)   # est déjà occupée chez lui, l'alerte va dans la touche FLIP)
        self.f_lbl = QFont("Segoe UI", 10, QFont.Bold)
        self.resize(KEY_W + 2 * PAD, KEY_H + 2 * PAD)

    def set(self, ab):
        self.ab = ab
        self.update()

    def paintEvent(self, _e):
        """Recouvre toute la touche FlipAB, à l'allure des boutons LV1 : « FLIP » + pastille A (bleue) / B (rouge)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), ROW_BG)                   # fond de la rangée : cache la touche d'origine en entier
        r = QRectF(PAD + 0.75, PAD + 0.75, KEY_W - 1.5, KEY_H - 1.5)
        p.setPen(QPen(QColor(255, 60, 40), 2.5) if self.alert else QPen(KEY_LINE, 1.5))   # contour LV1 (rouge : alerte)
        p.setBrush(KEY_BG)
        p.drawRoundedRect(r, KEY_R, KEY_R)
        p.setPen(QColor(TXT))
        p.setFont(self.f_lbl)
        p.drawText(QRectF(r.left() + 8, r.top(), r.width() / 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   "FLIP !" if self.alert else "FLIP")
        pill = QRectF(r.right() - 34, r.top() + 4, 30, r.height() - 8)
        p.setPen(Qt.NoPen)
        p.setBrush(red_gradient(pill) if self.ab == "B" else A_BLUE)
        p.drawRoundedRect(pill, 5, 5)
        p.setPen(QColor("#ffffff") if self.ab == "B" else QColor(PANEL))
        p.setFont(self.f)
        p.drawText(pill, Qt.AlignCenter, self.ab)


# ─── Rappel de pistes (demande de Joseph, 15/10) ─────────────────────────────────────────────────────────────────
# La X-Touch + Extender sont plus larges que l'écran : leurs tranches ne tombent pas sous celles de la LV1. Quand on
# touche un fader, un bandeau occupe la zone des faders de la LV1 (bas de l'écran) avec 17 cases ALIGNÉES SUR LA
# SURFACE : 8 cases (Extender) à gauche jusqu'à la séparation, 8 + 1 (X-Touch + master) à droite. Réglages dans
# xtouch_ecran.json (fractions / pixels de référence 1920x1080), valeurs par défaut tirées de la photo de Joseph.
# Blocs réglables à la main (`py xtouch_overlay_qt.py --reglage`) : Extender (8 cases), X-Touch (8), master (1),
# chacun [x début, x fin] en pixels de référence 1920 ; y0 / y1 = haut / bas du bandeau (référence 1080).
RECALL_DEFAULT = {"ext": [0.0, 941.0], "xt": [941.0, 1811.0], "master": [1811.0, 1920.0], "y0": 745.0, "y1": 1076.0,
                  "taille": "grand", "petit": [1017.0, 1076.0], "grand": [745.0, 1076.0]}
# Options d'affichage de la grande case (demande de Joseph du 15/10 : chacune activable dans le réglage, ADJUST)
RECALL_OPTIONS = [
    ("sel_button", "SELECT button", True),         # sélection = petit bouton vert « SELECT »
    ("sel_frame", "Selection frame", False),       # sélection = fond gris clair + contour jaune (comme la LV1)
    ("cap_alpha", "See-through fader", True),      # capuchon du fader un peu transparent (vumètre visible dessous)
    ("touch_dot", "Touch dot", True),              # fader touché : point bleu AU-DESSUS de la tranche (Joseph, 15/10)
    ("touch_outline", "Touch outline", True),      # fader touché : contour blanc de la case
]
# Deux hauteurs mémorisées (demande de Joseph, 15/10) : « petit » (nom, couleur, valeur, diode) et « grand »
# (présentation complète) ; `taille` = celle en cours, y0 / y1 = ses valeurs. Bascule : --taille petit|grand.
MINI_H = 140                 # bandeau moins haut que ça (px) : présentation « petit »
CFG_FILE = os.path.join((os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))),
                        "xtouch_ecran.json")
GREEN, AMBER, WARN = QColor("#3ddc84"), QColor("#f2b63b"), QColor("#ff5b4d")
# Couleurs de la tranche LV1 (relevées sur les captures de Joseph du 15/10)
LV1_BG, LV1_LINE, LV1_SEL, LV1_TXT = "#111111", "#a0a0a0", "#787878", "#e7e7e7"
LV1_KNOB, LV1_VAL_BG, LV1_BLUE, LV1_GREEN = "#525353", "#363636", "#38c9ff", "#8cff00"
LV1_SEL_GREEN, LV1_TOUCH = "#2fa84f", "#2b78e4"
DOT_PAD = 18                 # px transparents au-dessus du bandeau, pour le point de toucher
COMPACT_W = 70               # case plus étroite que ça (px) : présentation compacte (vumètres + fader par-dessus)
FADE_STEP = 0.16             # fondu du rappel : ~0,2 s à 30 ms par tour
# Bandeau ENTIÈREMENT OPAQUE (Joseph, 15/10 : le dégradé de transparence vers le haut a été essayé puis refusé)


def load_recall_cfg():
    cfg = json.loads(json.dumps(RECALL_DEFAULT))
    cfg["options"] = {k: d for k, _label, d in RECALL_OPTIONS}
    try:
        with open(CFG_FILE, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return cfg
    try:
        if "split" in raw and "ext" not in raw:      # ancien format (fraction de la largeur)
            sp = float(raw["split"]) * 1920.0
            unit = (1920.0 - sp) / 9.0
            cfg.update(ext=[0.0, sp], xt=[sp, sp + 8 * unit], master=[sp + 8 * unit, 1920.0])
        for k in ("ext", "xt", "master"):
            if k in raw:
                cfg[k] = [float(raw[k][0]), float(raw[k][1])]
        for k in ("y0", "y1"):
            if k in raw:
                cfg[k] = float(raw[k])
        for k in ("petit", "grand"):
            if k in raw:
                cfg[k] = [float(raw[k][0]), float(raw[k][1])]
        if raw.get("taille") in ("petit", "grand"):
            cfg["taille"] = raw["taille"]
        elif "petit" not in raw and cfg["y1"] - cfg["y0"] < MINI_H:      # ancien fichier : on range au bon endroit
            cfg["taille"] = "petit"
        if "petit" not in raw or "grand" not in raw:
            cfg[cfg["taille"]] = [cfg["y0"], cfg["y1"]]
        cfg["y0"], cfg["y1"] = cfg[cfg["taille"]]
        opts = raw.get("options") or {}
        for k, _label, _d in RECALL_OPTIONS:
            if k in opts:
                cfg["options"][k] = bool(opts[k])
    except (TypeError, ValueError, IndexError, KeyError):
        pass
    return cfg


def save_recall_cfg(cfg):
    cfg[cfg["taille"]] = [cfg["y0"], cfg["y1"]]          # la hauteur réglée va dans le profil en cours
    data = {k: cfg[k] for k in ("ext", "xt", "master", "y0", "y1", "taille", "petit", "grand", "options")}
    data["_aide"] = ("Rappel de pistes : blocs [x début, x fin] sur 1920 (Extender 8 cases, X-Touch 8, master 1), "
                     "y0 / y1 = haut / bas du bandeau sur 1080 (profil en cours). Deux hauteurs mémorisées : "
                     "petit / grand ; bascule : py xtouch_overlay_qt.py --taille petit|grand ; "
                     "réglage : py xtouch_overlay_qt.py --reglage")
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def recall_cells(w, cfg):
    """[(x, largeur)] des 17 cases en pixels du bandeau (largeur w) : 8 Extender, 8 X-Touch, 1 master."""
    k = w / 1920.0
    out = []
    for key, n in (("ext", 8), ("xt", 8), ("master", 1)):
        x0, x1 = cfg[key]
        step = (x1 - x0) / n
        out += [((x0 + step * i) * k, step * k) for i in range(n)]
    return out


def led_color(db):
    """Diode de vumètre (bandeau « petit ») : éteinte sous -50 dB, verte, ambre au-dessus de -12, rouge au-dessus de -3."""
    if db is None or db < -50:
        return QColor("#2a2e33")
    if db >= -3:
        return WARN
    if db >= -12:
        return AMBER
    return GREEN


def meter_frac(db):
    if db is None:
        return 0.0
    return max(0.0, min(1.0, (db + 60.0) / 70.0))      # -60 .. +10 dB


class StripRecall(QWidget):
    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.data = {}
        self.cfg = load_recall_cfg()
        self.f_name = QFont("Segoe UI", 11, QFont.Bold)
        self.f_val = QFont("Consolas", 15, QFont.Bold)
        self.f_tag = QFont("Segoe UI", 8, QFont.Bold)
        self.f_scale = QFont("Segoe UI", 7)
        self.f_mini = QFont("Segoe UI", 9, QFont.Bold)
        self.f_mini_val = QFont("Consolas", 10, QFont.Bold)

    def set(self, data):
        self.data = data or {}
        self.update()

    def paintEvent(self, _e):
        """Case : bandeau couleur + nom ; pastilles MUTE / SOLO / 48V / SEND ; gain X32 et pan ; fader avec repères
        à gauche, 1 ou 2 vumètres (stéréo) à droite ; valeur en grand en bas. Contour jaune = sélection LV1,
        blanc = fader touché (demande de Joseph : plus d'infos, fader, vumètres plus gros, 2 en stéréo)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cells = self.data.get("cells") or []
        touched = set(self.data.get("touched") or [])
        send = self.data.get("send")
        pad = DOT_PAD                                       # bande transparente du haut : points de toucher
        p.fillRect(QRectF(0, pad, self.width(), self.height() - pad), QColor(LV1_BG))   # fond plein, comme la LV1
        h = self.height() - pad
        dot = self.cfg.get("options", {}).get("touch_dot", True)
        for i, (cx, cw) in enumerate(recall_cells(self.width(), self.cfg)):
            if i >= len(cells):
                break
            mg = 2 if h < MINI_H else 4
            self.paint_cell(p, QRectF(cx + 2, pad + mg, cw - 4, h - 2 * mg), cells[i], i in touched, send)
            if dot and i in touched and cells[i]:            # point bleu au-dessus de la tranche touchée
                rd = min(8.0, pad / 2 - 1, cw / 4)
                p.setPen(QPen(QColor("#0b2f66"), 1.0))
                p.setBrush(QColor(LV1_TOUCH))
                p.drawEllipse(QPointF(cx + cw / 2, pad - rd - 1), rd, rd)

    def pill(self, p, r, text, fill, fg="#ffffff"):
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(fg))
        p.setFont(self.f_tag)
        p.drawText(r, Qt.AlignCenter, text)

    def paint_compact(self, p, r, c, hot=False):
        """Case étroite (< COMPACT_W, ex. master réglé à 36 px) au style LV1 (Joseph, 15/10 : « le fader master doit
        avoir le même style ») : bandeau couleur + nom court, vumètre(s) LV1 sur toute la hauteur, capuchon par-dessus,
        valeur en petit en bas."""
        opt = self.cfg.get("options", {})
        p.setPen(QPen(QColor("#ffffff") if (hot and opt.get("touch_outline", True)) else QColor(LV1_LINE),
                      2.0 if hot else 1.0))
        p.setBrush(QColor(LV1_BG))
        p.drawRoundedRect(r, 4, 4)
        col = QColor(c.get("color") or LV1_LINE)
        bar = QRectF(r.left() + 1, r.top() + 1, r.width() - 2, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRect(bar)
        dark = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue() > 110
        p.setPen(QColor(LV1_BG) if dark else QColor("#ffffff"))
        p.setFont(self.lv1_font(11))
        p.drawText(bar, Qt.AlignCenter, (c.get("name") or "")[:3])
        y = bar.bottom() + 4
        if c.get("mute"):
            mb = QRectF(r.left() + 3, y, r.width() - 6, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(225, 22, 32))
            p.drawRoundedRect(mb, 3, 3)
            p.setPen(QColor("#ffffff"))
            p.setFont(self.lv1_font(10))
            p.drawText(mb, Qt.AlignCenter, "M")
            y += 17
        bottom = r.bottom() - 18
        top_f, bot_f = y + 8, bottom - 8
        meters = c.get("meters") or [None]
        gap = 2.0
        bw = (r.width() - 12 - gap * (len(meters) - 1)) / len(meters)
        for k, db in enumerate(meters):
            m = QRectF(r.left() + 6 + k * (bw + gap), top_f, bw, bot_f - top_f)
            self.lv1_meter(p, m, db)
        if c.get("pos") is not None:
            self.lv1_cap(p, r.center().x(), bot_f - (bot_f - top_f) * c["pos"], r.width() - 6, 14, hot)
        p.setPen(QColor(LV1_TXT))
        p.setFont(self.lv1_font(10))
        p.drawText(QRectF(r.left() - 2, bottom, r.width() + 4, 16), Qt.AlignCenter, c.get("value", ""))

    def lv1_meter(self, p, m, db):
        """Une barre de vumètre LV1 (fond #363636, vert #8cff00, jaune puis rouge en haut), échelle du fader."""
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LV1_VAL_BG))
        p.drawRect(m)
        fr = self.fader_frac(db) if db is not None and db > -100 else 0.0
        if fr > 0:
            h = m.height() * fr
            g = QLinearGradient(m.bottomLeft(), m.topLeft())
            g.setColorAt(0, QColor(LV1_GREEN))
            g.setColorAt(max(0.0, self.fader_frac(-9) - 0.001), QColor(LV1_GREEN))
            g.setColorAt(self.fader_frac(-9), QColor(255, 210, 0))
            g.setColorAt(max(self.fader_frac(-9), self.fader_frac(0)), QColor(255, 60, 40))
            g.setColorAt(1, QColor(255, 60, 40))
            p.setBrush(g)
            p.drawRect(QRectF(m.left(), m.bottom() - h, m.width(), h))

    def paint_mini(self, p, r, c, hot, send):
        """Bandeau « petit » : couleur + nom en haut, valeur + diode(s) de vumètre en bas (2 en stéréo)."""
        sel = bool(c.get("sel"))
        p.setPen(QPen(QColor("#ffffff") if hot else (QColor(255, 242, 0) if sel else QColor(LINE2)),
                      2.0 if (hot or sel) else 1.0))
        p.setBrush(QColor("#1b1d20") if hot else QColor(PANEL))
        p.drawRoundedRect(r, 6, 6)
        col = QColor(c.get("color") or LINE2)
        top = QRectF(r.left(), r.top(), r.width(), r.height() * 0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.save()
        p.setClipPath(path)
        p.fillRect(top, col)
        p.restore()
        dark = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue() > 150
        p.setPen(QColor(PANEL) if dark else QColor("#ffffff"))
        p.setFont(self.f_mini)
        name = c.get("name", "")
        p.drawText(top.adjusted(3, 0, -3, 0), Qt.AlignCenter, name if r.width() >= COMPACT_W else name[:3])
        bot = QRectF(r.left(), top.bottom(), r.width(), r.bottom() - top.bottom())
        meters = c.get("meters") or [None]
        d = max(6.0, min(10.0, bot.height() * 0.42))
        lx = bot.right() - 5 - d * len(meters) - 3 * (len(meters) - 1)
        for k, db in enumerate(meters):
            p.setPen(Qt.NoPen)
            p.setBrush(led_color(db))
            p.drawEllipse(QRectF(lx + k * (d + 3), bot.center().y() - d / 2, d, d))
        x0 = bot.left() + 4
        if c.get("mute"):
            p.setPen(QColor(225, 22, 32))
            p.setFont(self.f_mini)
            p.drawText(QRectF(x0, bot.top(), 14, bot.height()), Qt.AlignVCenter | Qt.AlignLeft, "M")
            x0 += 14
        p.setPen(QColor("#ff8a80") if (send and c.get("send_off")) else QColor(TXT))
        p.setFont(self.f_mini_val)
        p.drawText(QRectF(x0, bot.top(), lx - x0 - 2, bot.height()), Qt.AlignCenter,
                   ("> " if send else "") + c.get("value", ""))

    def paint_cell(self, p, r, c, hot, send):
        if c and self.height() - DOT_PAD < MINI_H:
            self.paint_mini(p, r, c, hot, send)
            return
        if c and r.width() < COMPACT_W:
            self.paint_compact(p, r, c, hot)
            return
        self.paint_lv1(p, r, c, hot, send)

    def paint_lv1(self, p, r, c, hot, send):
        """Grande case = tranche de la LV1, au plus près (demande de Joseph du 15/10 : « exactement le même design que
        la LV1 », fader posé sur le vumètre). Couleurs relevées sur ses captures : fond #111111, contour #a0a0a0,
        bouton de pan #525353 (arc bleu #38c9ff), MUTE, valeur #38c9ff sur #363636, niveau du vumètre, fader sur le
        vumètre vert #8cff00 avec l'échelle LV1 à droite, bandeau couleur + nom, bouton casque (solo).
        Sélection : fond #787878 + contour jaune ; fader touché : contour blanc."""
        opt = self.cfg.get("options", {})
        sel = bool(c and c.get("sel"))
        frame_sel = sel and opt.get("sel_frame")
        hot_line = hot and opt.get("touch_outline", True)
        H, W = r.height(), r.width()
        p.setPen(QPen(QColor("#ffffff") if hot_line else (QColor(255, 242, 0) if frame_sel else QColor(LV1_LINE)),
                      2.0 if (hot_line or frame_sel) else 1.0))
        p.setBrush(QColor(LV1_SEL) if frame_sel else QColor(LV1_BG))
        p.drawRoundedRect(r, 4, 4)
        if not c:
            return
        x0, y0, cx = r.left(), r.top(), r.center().x()
        off = bool(send and c.get("send_off"))
        # bouton de pan (s'il est connu) : arc bleu depuis le haut jusqu'à la position
        pv = c.get("pan_v")
        kr = min(H * 0.062, W * 0.24)
        ky = y0 + H * 0.085
        if pv is not None:
            p.setPen(QPen(QColor("#2a2a2a"), 1.5))
            p.setBrush(QColor(LV1_KNOB))
            p.drawEllipse(QRectF(cx - kr, ky - kr, 2 * kr, 2 * kr))
            ang = max(-1.0, min(1.0, pv)) * 135.0
            if abs(ang) > 0.5:
                arc = QRectF(cx - kr - 3, ky - kr - 3, 2 * kr + 6, 2 * kr + 6)
                p.setPen(QPen(QColor(LV1_BLUE), 3.0, Qt.SolidLine, Qt.FlatCap))
                p.setBrush(Qt.NoBrush)
                p.drawArc(arc, 90 * 16, int(-ang * 16))
            a = math.radians(ang)
            p.setPen(QPen(QColor(LV1_TXT), 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx + math.sin(a) * kr * 0.25, ky - math.cos(a) * kr * 0.25),
                       QPointF(cx + math.sin(a) * kr * 0.92, ky - math.cos(a) * kr * 0.92))
        # MUTE (rouge si coupé)
        mb = QRectF(x0 + W * 0.14, y0 + H * 0.185, W * 0.72, H * 0.06)
        p.setPen(QPen(QColor(LV1_LINE), 1.0))
        p.setBrush(QColor(225, 22, 32) if c.get("mute") else Qt.NoBrush)
        p.drawRoundedRect(mb, 3, 3)
        p.setPen(QColor(LV1_TXT))
        p.setFont(self.lv1_font(H * 0.042))
        p.drawText(mb, Qt.AlignCenter, "MUTE")
        # valeur (fader, ou niveau d'envoi en sends on fader)
        vb = QRectF(x0 + W * 0.14, y0 + H * 0.258, W * 0.72, H * 0.062)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LV1_VAL_BG))
        p.drawRect(vb)
        p.setPen(QColor("#6b7378") if off else QColor(LV1_BLUE))
        p.setFont(self.lv1_font(H * 0.05))
        p.drawText(vb, Qt.AlignCenter, c.get("value", ""))
        # niveau du vumètre (comme le petit chiffre blanc de la LV1)
        mv = c.get("meter")
        p.setPen(QColor(LV1_TXT))
        p.setFont(self.lv1_font(H * 0.038))
        p.drawText(QRectF(x0, y0 + H * 0.322, W, H * 0.04), Qt.AlignCenter,
                   "-Inf" if mv is None or mv <= -100 else "%.1f" % mv)
        # zone fader : vumètre(s) sous le fader, échelle LV1 à droite
        top_f, bot_f = y0 + H * 0.385, y0 + H * 0.775
        if sel and opt.get("sel_button", True):           # sélection : petit bouton vert « SELECT » (Joseph, 15/10)
            sb = QRectF(x0 + W * 0.04, y0 + H * 0.324, W * 0.36, H * 0.052)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(LV1_SEL_GREEN))
            p.drawRoundedRect(sb, 3, 3)
            p.setPen(QColor("#ffffff"))
            p.setFont(self.lv1_font(min(H * 0.04, W * 0.095)))
            p.drawText(sb, Qt.AlignCenter, "SELECT")
        fx = x0 + W * 0.46
        meters = c.get("meters") or [None]
        bw = max(4.0, W * 0.075)
        gap = 3.0
        tot = bw * len(meters) + gap * (len(meters) - 1)
        for k, db in enumerate(meters):
            self.lv1_meter(p, QRectF(fx - tot / 2 + k * (bw + gap), top_f, bw, bot_f - top_f), db)
        p.setFont(self.lv1_font(H * 0.034))
        sx = x0 + W * 0.66
        for mark, lab in ((10, "10"), (0, "0"), (-10, "10"), (-20, "20"), (-30, "30"), (-50, "50"), (None, "\u221e")):
            yy = bot_f - (bot_f - top_f) * self.fader_frac(mark)
            p.setPen(QColor(LV1_TXT))
            p.drawLine(QPointF(sx, yy), QPointF(sx + W * 0.05, yy))
            p.drawText(QRectF(sx + W * 0.07, yy - 7, W * 0.27, 14), Qt.AlignLeft | Qt.AlignVCenter, lab)
        if send:                                         # « Send Level » vertical, en vert (gris si l'envoi est coupé)
            p.save()
            p.translate(x0 + W * 0.13, (top_f + bot_f) / 2)
            p.rotate(-90)
            p.setPen(QColor("#5f6b55") if off else QColor(LV1_GREEN))
            p.setFont(self.lv1_font(H * 0.04))
            p.drawText(QRectF(-(bot_f - top_f) / 2, -9, bot_f - top_f, 18), Qt.AlignCenter, "Send Level")
            p.restore()
        pos = c.get("pos")
        if pos is not None:
            self.lv1_cap(p, fx, bot_f - (bot_f - top_f) * pos, max(18.0, W * 0.34), max(16.0, H * 0.075), hot)
        # bandeau à la couleur du canal : nom (le numéro LV1 à droite)
        col = QColor(c.get("color") or LV1_LINE)
        bar = QRectF(x0 + 1, y0 + H * 0.815, W - 2, H * 0.075)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRect(bar)
        dark = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue() > 110
        p.setPen(QColor(LV1_BG) if dark else QColor("#ffffff"))
        num = c.get("num") or ""
        p.setFont(self.lv1_font(H * 0.04))
        nw = p.fontMetrics().horizontalAdvance(num) + 6 if num else 0
        if num:
            p.drawText(bar.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter, num)
        name = p.fontMetrics().elidedText(c.get("name", ""), Qt.ElideRight, int(bar.width() - nw - 6))
        p.drawText(bar.adjusted(4, 0, -nw, 0), Qt.AlignLeft | Qt.AlignVCenter, name)
        # bouton casque = solo (jaune si actif)
        cb = QRectF(x0 + W * 0.18, y0 + H * 0.905, W * 0.64, H * 0.07)
        solo = bool(c.get("solo"))
        p.setPen(QPen(QColor(LV1_LINE), 1.0))
        p.setBrush(QColor(255, 242, 0) if solo else Qt.NoBrush)
        p.drawRoundedRect(cb, 4, 4)
        self.paint_headphones(p, cb.center(), cb.height() * 0.62, QColor(LV1_BG) if solo else QColor(LV1_TXT))

    def lv1_cap(self, p, cx, cy, cw, ch_, hot):
        """Capuchon du fader LV1 ; un peu transparent (option) pour voir le vumètre dessous ; flèches si touché."""
        opt = self.cfg.get("options", {})
        cap = QRectF(cx - cw / 2, cy - ch_ / 2, cw, ch_)
        p.save()
        if opt.get("cap_alpha", True):
            p.setOpacity(0.62)
        g = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        g.setColorAt(0, QColor("#d2d2d2"))
        g.setColorAt(0.45, QColor("#9b9b9b"))
        g.setColorAt(1, QColor("#6e6e6e"))
        p.setPen(QPen(QColor("#3a3a3a"), 1.0))
        p.setBrush(g)
        p.drawRoundedRect(cap, 3, 3)
        p.setOpacity(1.0)
        p.setPen(QPen(QColor("#1e1e1e"), 1.6))
        p.drawLine(QPointF(cap.left() + 3, cy), QPointF(cap.right() - 3, cy))
        p.restore()

    def paint_headphones(self, p, ctr, size, color):
        p.setPen(QPen(color, max(1.5, size * 0.12), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        rr = size / 2
        p.drawArc(QRectF(ctr.x() - rr, ctr.y() - rr, 2 * rr, 2 * rr), 0, 180 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        w = size * 0.2
        for sx in (-1, 1):
            p.drawRoundedRect(QRectF(ctr.x() + sx * rr - w / 2, ctr.y() - size * 0.05, w, size * 0.42), 1.5, 1.5)

    def lv1_font(self, px):
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(max(8, int(px)))
        return f

    def fader_frac(self, db):
        """Position (0..1) d'un repère dB sur le petit fader, avec la courbe du pont (points fournis)."""
        curve = self.data.get("curve") or []
        if db is None or not curve:
            return 0.0 if db is None else max(0.0, min(1.0, (db + 60.0) / 70.0))
        if db >= curve[0][0]:
            return curve[0][1]
        for (d1, p1), (d2, p2) in zip(curve, curve[1:]):
            if d2 <= db <= d1:
                return p2 + (p1 - p2) * (db - d2) / (d1 - d2)
        return 0.0


class RecallSetup(QWidget):
    """Réglage à la main des 3 blocs (Extender 8, X-Touch 8, master 1) et du haut / bas du bandeau.
    Glisser un BORD de bloc pour l'étirer, l'INTÉRIEUR pour le déplacer, la ligne du haut ou du bas pour la hauteur.
    Entrée ou bouton ENREGISTRER : sauve dans xtouch_ecran.json ; Échap ou ANNULER : quitte sans rien changer."""
    BLOCKS = (("ext", "EXTENDER", 8, QColor("#13a9af")), ("xt", "X-TOUCH", 8, QColor("#7f77dd")),
              ("master", "MASTER", 1, QColor("#f2b63b")))
    GRAB = 18

    def __init__(self, rect, on_done=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.on_done = on_done or QApplication.quit       # ouvert par le bouton ADJUST : retour au rappel
        self.cfg = load_recall_cfg()
        self.drag = None
        x, y, w, h = rect
        self.setGeometry(x, y, w, h)
        self.k, self.ky = w / 1920.0, h / 1080.0
        self.f = QFont("Segoe UI", 12, QFont.Bold)
        self.f_big = QFont("Segoe UI", 14, QFont.Bold)

    def buttons(self):
        cx = self.width() / 2
        return {"save": QRectF(cx - 210, 40, 200, 46), "cancel": QRectF(cx + 10, 40, 200, 46)}

    def toggles(self):
        """Interrupteurs des options d'affichage (RECALL_OPTIONS), en ligne sous la consigne."""
        w, gap = 190, 10
        x = self.width() / 2 - (len(RECALL_OPTIONS) * (w + gap) - gap) / 2
        return {k: QRectF(x + i * (w + gap), 140, w, 36) for i, (k, _l, _d) in enumerate(RECALL_OPTIONS)}

    def block_rect(self, key):
        x0, x1 = self.cfg[key]
        return QRectF(x0 * self.k, self.cfg["y0"] * self.ky, (x1 - x0) * self.k, (self.cfg["y1"] - self.cfg["y0"]) * self.ky)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        for key, label, n, col in self.BLOCKS:
            r = self.block_rect(key)
            fill = QColor(col)
            fill.setAlpha(70)
            p.setPen(QPen(col, 3))
            p.setBrush(fill)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 160), 1, Qt.DashLine))
            for i in range(1, n):
                xx = r.left() + r.width() * i / n
                p.drawLine(int(xx), int(r.top() + 8), int(xx), int(r.bottom() - 8))
            p.setPen(QColor("#ffffff"))
            p.setFont(self.f)
            p.drawText(r, Qt.AlignCenter, "%s (%d)\n%d - %d" % (label, n, round(self.cfg[key][0]), round(self.cfg[key][1])))
        p.setFont(self.f_big)
        for name, r in self.buttons().items():
            p.setPen(Qt.NoPen)
            p.setBrush(red_gradient(r) if name == "save" else QColor(PANEL))
            p.drawRoundedRect(r, 10, 10)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignCenter, "ENREGISTRER" if name == "save" else "ANNULER")
        p.setPen(QColor(TXT))
        p.setFont(self.f)
        p.drawText(QRectF(0, 96, self.width(), 30), Qt.AlignCenter,
                   "Glisse les bords pour étirer, l'intérieur pour déplacer, le haut / bas pour la hauteur")
        opts = self.cfg.get("options", {})
        for k, label, _d in RECALL_OPTIONS:
            r = self.toggles()[k]
            on = opts.get(k, False)
            p.setPen(QPen(QColor(LV1_LINE), 1.0))
            p.setBrush(QColor(LV1_BLUE) if on else QColor(PANEL))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(PANEL) if on else QColor(TXT))
            p.drawText(r, Qt.AlignCenter, ("✓ " if on else "") + label)

    def hit(self, pos):
        for name, r in self.buttons().items():
            if r.contains(pos):
                return ("button", name)
        for k, r in self.toggles().items():
            if r.contains(pos):
                return ("toggle", k)
        y0, y1 = self.cfg["y0"] * self.ky, self.cfg["y1"] * self.ky
        for key, _l, _n, _c in self.BLOCKS:
            r = self.block_rect(key)
            if r.adjusted(-self.GRAB, -self.GRAB, self.GRAB, self.GRAB).contains(pos):
                if abs(pos.x() - r.left()) < self.GRAB:
                    return ("edge", key, 0)
                if abs(pos.x() - r.right()) < self.GRAB:
                    return ("edge", key, 1)
                if abs(pos.y() - y0) < self.GRAB:
                    return ("y", "y0")
                if abs(pos.y() - y1) < self.GRAB:
                    return ("y", "y1")
                return ("move", key)
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        h = self.hit(pos)
        if h and h[0] == "toggle":                      # option d'affichage : bascule (enregistrée avec ENREGISTRER)
            self.cfg.setdefault("options", {})[h[1]] = not self.cfg.get("options", {}).get(h[1], False)
            self.update()
            return
        if h and h[0] == "button":
            if h[1] == "save":
                save_recall_cfg(self.cfg)
            self.on_done()
            return
        self.drag = (h, pos, json.loads(json.dumps(self.cfg))) if h else None

    def mouseMoveEvent(self, e):
        if not self.drag:
            return
        h, start, orig = self.drag
        dx = (e.position().x() - start.x()) / self.k
        dy = (e.position().y() - start.y()) / self.ky
        if h[0] == "edge":
            v = orig[h[1]][h[2]] + dx
            self.cfg[h[1]][h[2]] = max(0.0, min(1920.0, v))
        elif h[0] == "move":
            w = orig[h[1]][1] - orig[h[1]][0]
            x0 = max(0.0, min(1920.0 - w, orig[h[1]][0] + dx))
            self.cfg[h[1]] = [x0, x0 + w]
        elif h[0] == "y":
            self.cfg[h[1]] = max(0.0, min(1080.0, orig[h[1]] + dy))
        self.update()

    def mouseReleaseEvent(self, _e):
        self.drag = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            save_recall_cfg(self.cfg)
            self.on_done()
        elif e.key() == Qt.Key_Escape:
            self.on_done()


# Boutons du rappel de pistes (demande de Joseph, 15/10 : basculer petit / grand et entrer dans le réglage depuis
# l'écran ; base du futur bouton « agrandir / rapetisser » de l'appli). Deux boutons l'un sous l'autre dans la zone
# vide en bas à gauche de la LV1 (sous Output L/R, endroit montré par Joseph sur sa capture ; bandeau grand : ils
# remontent au-dessus), BTN_RECT en pixels de référence 1920x1080 (zone rouge de Joseph, capture du 15/10) :
# lv1/layout.py.
# Ils font PARTIE DU BANDEAU (Joseph) : même apparition, même disparition, même fondu ; pour les atteindre, on tient
# un fader et on appuie sur le bouton à l'écran tactile. Seule fenêtre du rappel qui reçoit les clics, sans prendre
# le focus de la LV1.


class RecallButtons(QWidget):
    def __init__(self, on_size, on_adjust):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.on_size, self.on_adjust = on_size, on_adjust
        self.taille, self.hover = "grand", None
        self.f_icon = QFont("Segoe UI Symbol", 13, QFont.Bold)
        self.f = QFont("Segoe UI", 7, QFont.Bold)

    def zones(self):
        w, h = self.width(), self.height()
        half = (h - 6) / 2.0
        return {"size": QRectF(1, 1, w - 2, half), "adjust": QRectF(1, half + 5, w - 2, half)}

    def set_taille(self, taille):
        if taille != self.taille:
            self.taille = taille
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        big = self.taille == "grand"
        for key, r in self.zones().items():
            p.setPen(QPen(QColor(A_BLUE) if key == self.hover else QColor(LINE2), 1.5))
            p.setBrush(QColor("#25282c") if key == self.hover else QColor(PANEL))
            p.drawRoundedRect(r, 8, 8)
            if key == "size":                              # action proposée : rapetisser si grand, agrandir si petit
                icon, label = ("\u25bc", "SMALL") if big else ("\u25b2", "LARGE")
                col = A_BLUE
            else:
                icon, label, col = "\u2699", "ADJUST", QColor(TXT)
            top = QRectF(r.left(), r.top() + 4, r.width(), r.height() * 0.55)
            p.setPen(col)
            p.setFont(self.f_icon)
            p.drawText(top, Qt.AlignCenter, icon)
            p.setPen(QColor(TXT))
            p.setFont(self.f)
            p.drawText(QRectF(r.left(), top.bottom() - 2, r.width(), r.bottom() - top.bottom()), Qt.AlignCenter, label)

    def hit(self, pos):
        for key, r in self.zones().items():
            if r.contains(pos):
                return key
        return None

    def mouseMoveEvent(self, e):
        h = self.hit(e.position())
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        h = self.hit(e.position())
        if h == "size":
            self.on_size("petit" if self.taille == "grand" else "grand")
        elif h == "adjust":
            self.on_adjust()


class Bus(QObject):
    msg = Signal(dict)


class Overlay:
    def __init__(self, mixer=1, rect_fn=None):
        # La pastille FLIP n'apparaît que si la LV1 (ou une de ses fenêtres / boîtes de dialogue) est au premier
        # plan (Joseph, 15/10 : elle restait par-dessus les autres programmes). Rappel de pistes et sends on fader
        # restent affichés même LV1 en arrière-plan (choix de Joseph).
        self.demo = rect_fn is not None
        self.pid_fn = (lambda: None) if rect_fn else (lambda: lv1_pid(mixer))     # démo : toujours affiché
        self.pid, self.lv1_rect, self.front = None, None, True
        self.rect_fn = rect_fn or (lambda: lv1_rect(mixer))
        self.banner, self.frame = Banner(), Frame()
        self.badge, self.ab, self.ab_key = AbBadge(), None, None
        self.warn_text = None
        self.toast, self.toast_since = LayerToast(), None
        self.recall, self.recall_on = StripRecall(), False
        self.recall_alpha, self.cfg_mtime, self.cfg_t = 0.0, None, 0.0
        self.buttons = RecallButtons(self.set_taille, self.open_setup)
        self.setup = None
        self.mixer = mixer
        self.state = None            # (text, sub, color) voulu
        self.since = 0.0
        self.rect, self.rect_t = None, 0.0
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)

    def set_taille(self, taille):
        """Bouton SMALL / LARGE : change de hauteur mémorisée (enregistrée dans xtouch_ecran.json)."""
        cfg = load_recall_cfg()
        cfg["taille"] = taille
        cfg["y0"], cfg["y1"] = cfg[taille]
        save_recall_cfg(cfg)
        self.recall.cfg = cfg
        self.recall.update()
        self.buttons.set_taille(taille)

    def open_setup(self):
        """Bouton ADJUST : réglage à la main (le même que --reglage) ; rappel et boutons cachés pendant ce temps."""
        if self.setup:
            return
        self.setup = RecallSetup(self.rect or lv1_rect(self.mixer) or (0, 0, 1920, 1080), on_done=self.close_setup)
        self.setup.show()
        self.setup.raise_()
        self.setup.activateWindow()

    def close_setup(self):
        self.setup.hide()
        self.setup.deleteLater()
        self.setup = None
        self.recall.cfg = load_recall_cfg()
        self.recall.update()

    def tick_buttons(self, now):
        if self.recall_alpha <= 0.0 or not self.rect:          # suit le bandeau : même fondu
            if self.buttons.isVisible():
                self.buttons.hide()
            return
        x, y, w, h = self.rect
        sx, sy = w / 1920.0, h / 1080.0
        bx, by, bw, bh = BTN_RECT
        # bandeau grand : les boutons remontent au-dessus, y compris de la bande des points de toucher (DOT_PAD)
        by = min(by, self.recall.cfg["y0"] - DOT_PAD - bh - 4)
        geo = (x + round(bx * sx), y + round(by * sy), round(bw * sx), round(bh * sy))
        if self.buttons.geometry().getRect() != geo:
            self.buttons.setGeometry(*geo)
        self.buttons.set_taille(self.recall.cfg["taille"])
        self.buttons.setWindowOpacity(self.recall_alpha)
        if not self.buttons.isVisible():
            self.buttons.show()
        self.buttons.raise_()                                   # toujours au-dessus du bandeau

    def tick_recall(self):
        now = time.time()
        if now - self.cfg_t > 1.0:                   # réglage modifié (--reglage) : pris en compte à chaud
            self.cfg_t = now
            try:
                mt = os.path.getmtime(CFG_FILE)
            except OSError:
                mt = None
            if mt != self.cfg_mtime:
                self.cfg_mtime = mt
                self.recall.cfg = load_recall_cfg()
                self.recall.update()
        target = 1.0 if (self.recall_on and self.rect and not self.setup) else 0.0     # caché pendant le réglage
        if self.recall_alpha == target == 0.0:
            return
        if self.recall_alpha < target:              # fondu vers la cible, sans la dépasser (bug du 15/10 : à 100 %
            self.recall_alpha = min(target, self.recall_alpha + FADE_STEP)   # il oscillait 84 % <-> 100 %)
        elif self.recall_alpha > target:
            self.recall_alpha = max(target, self.recall_alpha - FADE_STEP)
        if self.recall_alpha <= 0.0 or not self.rect:      # LV1 plus au premier plan : caché tout de suite
            self.recall_alpha = 0.0
            self.recall.hide()
            return
        x, y, w, h = self.rect
        cfg = self.recall.cfg
        geo = (x, y + round(cfg["y0"] * h / 1080.0) - DOT_PAD, w, round((cfg["y1"] - cfg["y0"]) * h / 1080.0) + DOT_PAD)
        if self.recall.geometry().getRect() != geo:
            self.recall.setGeometry(*geo)
        self.recall.setWindowOpacity(self.recall_alpha)     # fondu d'apparition / disparition
        if not self.recall.isVisible():
            self.recall.show()
            self.recall.raise_()

    def tick_badge(self, now):
        if not self.ab or self.ab_key is None or not self.rect or not self.front:
            if self.badge.isVisible():
                self.badge.hide()
            return
        x, y, w, h = self.rect
        sx, sy = w / 1920.0, h / 1080.0
        bx = x + round((KEY_L + UK_PITCH * self.ab_key - PAD) * sx)
        by = y + round((KEY_T - PAD) * sy)
        if self.badge.pos().x() != bx or self.badge.pos().y() != by:
            self.badge.move(bx, by)
        # Toujours OPAQUE (Joseph, 15/10 : la respiration en semi-transparence n'est pas esthétique)
        if self.badge.windowOpacity() != 1.0:
            self.badge.setWindowOpacity(1.0)
        if not self.badge.isVisible():
            self.badge.show()

    def tick_toast(self, now):
        age = None if self.toast_since is None else (now - self.toast_since) * 1000
        if age is None or age >= TOAST_MS or not self.rect:
            if self.toast.isVisible():
                self.toast.hide()
            return
        x, y, w, h = self.rect
        tx = x + round(TOAST_RIGHT * w / 1920.0) - TOAST_W
        ty = y + round(TOAST_BOTTOM * h / 1080.0) - TOAST_H
        if self.toast.pos().x() != tx or self.toast.pos().y() != ty:
            self.toast.move(tx, ty)
        self.toast.setWindowOpacity(max(0.0, min(1.0, age / FADE_MS, (TOAST_MS - age) / FADE_MS)))
        if not self.toast.isVisible():
            self.toast.show()
        self.toast.raise_()                          # au-dessus du rappel de pistes

    def on_msg(self, m):
        if m.get("quit"):
            QApplication.quit()
            return
        if "recall" in m:                            # rappel de pistes : {"cells": [...], "touched": [...], "send"} | null
            self.recall_on = bool(m["recall"])
            if self.recall_on:
                self.recall.set(m["recall"])
            return
        if "mixer" in m:                             # {"mixer": 1 | 2} : Mixer suivi par le pont (18/10)
            n = 2 if m["mixer"] == 2 else 1
            if n != self.mixer:
                self.mixer = n
                if not self.demo:
                    self.rect_fn = lambda: lv1_rect(n)
                    self.pid_fn = lambda: lv1_pid(n)
                self.rect_t = 0.0                        # recalcul de la fenêtre au prochain tour
            return
        if "layer" in m:                             # {"layer": {"name": "Ch 17-32", "sub": "Mixer 2"}} : notification
            if m["layer"]:
                self.toast.set(m["layer"].get("name", ""), m["layer"].get("sub"))
                self.toast_since = time.time()
            return
        if "warn" in m:                              # {"warn": "B PATCH / 3 OFF" | null} : diagonale B cassée
            self.warn_text = m["warn"]
            self.badge.alert = bool(self.warn_text)  # -> contour rouge + « FLIP ! » sur la touche FLIP
            self.badge.update()
            return
        if "ab" in m:                                # {"ab": "A" | "B" | null, "key": n° de la User Key 0..15}
            self.ab, self.ab_key = m.get("ab"), m.get("key")
            if self.ab:
                self.badge.set(self.ab)
            return
        new = (m.get("text"), m.get("sub"), m.get("color")) if m.get("text") else None
        if new != self.state:
            self.state, self.since = new, time.time()
            if new:
                self.banner.set(*new)
                label = new[0] + ("  " + new[1] if new[1] else "")
                self.frame.set(label, new[2])

    def tick(self):
        now = time.time()
        if now - self.rect_t > 1.0:
            self.lv1_rect, self.rect_t = self.rect_fn(), now
            self.pid = self.pid_fn()
        self.front = self.pid is None or foreground_pid() in (self.pid, os.getpid())
        self.rect = self.lv1_rect
        self.tick_badge(now)
        self.tick_recall()
        self.tick_buttons(now)
        self.tick_toast(now)
        if not self.state or not self.rect:
            for w in (self.banner, self.frame):
                if w.isVisible():
                    w.hide()
            return
        x, y, w, h = self.rect
        age = (now - self.since) * 1000
        if age < BANNER_MS:
            self.frame.hide()
            bw, bh = self.banner.width(), self.banner.height()
            self.banner.move(x + (w - bw) // 2, y + (h - bh) // 2)
            fade = min(1.0, age / FADE_MS, (BANNER_MS - age) / FADE_MS)
            self.banner.setWindowOpacity(max(0.0, fade))
            if not self.banner.isVisible():
                self.banner.show()
        else:
            self.banner.hide()
            if self.frame.geometry().getRect() != (x, y, w, h):
                self.frame.setGeometry(x, y, w, h)
            breath = 0.5 + 0.5 * math.sin(2 * math.pi * now / BREATH_S)
            k = min(1.0, (age - BANNER_MS) / FADE_MS)
            self.frame.setWindowOpacity(k * (FRAME_MIN + (FRAME_MAX - FRAME_MIN) * breath))
            if not self.frame.isVisible():
                self.frame.show()


def main():
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    demo = "--demo" in sys.argv
    mixer = 2 if "--mixer=2" in sys.argv else 1
    if "--taille" in sys.argv:                       # bascule petit / grand (le pont la prend en compte à chaud)
        i = sys.argv.index("--taille")
        want = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        cfg = load_recall_cfg()
        if want not in ("petit", "grand"):
            want = "grand" if cfg["taille"] == "petit" else "petit"
        cfg["taille"] = want
        cfg["y0"], cfg["y1"] = cfg[want]
        save_recall_cfg(cfg)
        print("Rappel de pistes : taille %s (%d - %d)" % (want, cfg["y0"], cfg["y1"]))
        return 0
    if "--reglage" in sys.argv:                      # réglage à la main des blocs du rappel de pistes
        setup = RecallSetup(lv1_rect(mixer) or (0, 0, 1920, 1080))
        setup.show()
        setup.raise_()
        setup.activateWindow()
        return app.exec()
    ov = Overlay(mixer, (lambda: lv1_rect(mixer) or (0, 0, 1280, 720)) if demo else None)
    bus = Bus()
    bus.msg.connect(ov.on_msg)
    if demo:
        def script():
            time.sleep(0.5)
            bus.msg.emit({"text": "SELECT AN AUX", "sub": "", "color": None})
            time.sleep(3.5)
            bus.msg.emit({"text": "FX 1", "sub": "Reverb", "color": "#7f77dd"})
            bus.msg.emit({"ab": "A", "key": 15})
            time.sleep(3)
            bus.msg.emit({"ab": "B", "key": 15})
            time.sleep(3)
            bus.msg.emit({"quit": True})
    else:
        def script():                              # lignes JSON sur stdin ; fin de stdin = le pont est arrêté
            for line in sys.stdin:
                try:
                    bus.msg.emit(json.loads(line))
                except ValueError:
                    pass
            bus.msg.emit({"quit": True})
    threading.Thread(target=script, daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
