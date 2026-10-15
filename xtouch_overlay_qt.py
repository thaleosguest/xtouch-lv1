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

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

PANEL, LINE2, TXT, MUT = "#111213", "#3a3e43", "#e9edf0", "#8c939a"
RED_TOP, RED_BOT = QColor(255, 120, 105), QColor(225, 22, 32)
FADE_MS = 260
BANNER_MS = 2500
BREATH_S = 2.4                      # période de la respiration du cadre
FRAME_MIN, FRAME_MAX = 0.35, 0.95
BORDER = 5
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


def window_pid(hwnd):
    import ctypes
    pid = ctypes.c_ulong(0)
    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_pid():
    """Processus de la fenêtre au premier plan (0 si inconnu)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = ctypes.c_void_p
        h = u.GetForegroundWindow()
        return window_pid(h) if h else 0
    except Exception:
        return 0


def lv1_pid(mixer=1):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import lv1_clic
        h, _ = lv1_clic.lv1_window(mixer)
        return window_pid(h) if h else None
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
# entrées sont sur A ou B). Rangée des User Keys, visible sur toutes les pages : touche k = x 145+96k .. 229+96k,
# y 62..90 (1920x1080, relevé du 15/10). Pastille dans la partie droite de la touche.
UK_X0, UK_PITCH, UK_W, UK_Y0, UK_H = 145, 96, 84, 62, 28
# Touche d'origine relevée au pixel (15/10) : contour clair (160) x 144+96k .. 230+96k, y 61..90, coins ~5 px, intérieur
# (17,17,17), fond de la rangée (71,71,71). La pastille la recopie en débordant de PAD px : rien ne transparaît.
KEY_L, KEY_T, KEY_W, KEY_H, KEY_R, PAD = 144, 61, 87, 30, 5, 2
ROW_BG, KEY_BG, KEY_LINE = QColor(71, 71, 71), QColor(17, 17, 17), QColor(160, 160, 160)
A_BLUE = QColor(56, 201, 255)          # bouton A/B actif de la LV1


class AbBadge(QWidget):
    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.ab = "A"
        self.f = QFont("Segoe UI", 11, QFont.Bold)
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
        p.setPen(QPen(KEY_LINE, 1.5))                     # même contour que les touches de la LV1
        p.setBrush(KEY_BG)
        p.drawRoundedRect(r, KEY_R, KEY_R)
        p.setPen(QColor(TXT))
        p.setFont(self.f_lbl)
        p.drawText(QRectF(r.left() + 8, r.top(), r.width() / 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter, "FLIP")
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
# Deux hauteurs mémorisées (demande de Joseph, 15/10) : « petit » (nom, couleur, valeur, diode) et « grand »
# (présentation complète) ; `taille` = celle en cours, y0 / y1 = ses valeurs. Bascule : --taille petit|grand.
MINI_H = 140                 # bandeau moins haut que ça (px) : présentation « petit »
CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xtouch_ecran.json")
GREEN, AMBER, WARN = QColor("#3ddc84"), QColor("#f2b63b"), QColor("#ff5b4d")
COMPACT_W = 70               # case plus étroite que ça (px) : présentation compacte (vumètres + fader par-dessus)
FADE_STEP = 0.16             # fondu du rappel : ~0,2 s à 30 ms par tour
# Bandeau ENTIÈREMENT OPAQUE (Joseph, 15/10 : le dégradé de transparence vers le haut a été essayé puis refusé)


def load_recall_cfg():
    cfg = json.loads(json.dumps(RECALL_DEFAULT))
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
    except (TypeError, ValueError, IndexError, KeyError):
        pass
    return cfg


def save_recall_cfg(cfg):
    cfg[cfg["taille"]] = [cfg["y0"], cfg["y1"]]          # la hauteur réglée va dans le profil en cours
    data = {k: cfg[k] for k in ("ext", "xt", "master", "y0", "y1", "taille", "petit", "grand")}
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
        p.fillRect(self.rect(), QColor(8, 9, 10))           # fond plein
        for i, (cx, cw) in enumerate(recall_cells(self.width(), self.cfg)):
            if i >= len(cells):
                break
            mg = 2 if self.height() < MINI_H else 4
            self.paint_cell(p, QRectF(cx + 2, mg, cw - 4, self.height() - 2 * mg), cells[i], i in touched, send)

    def pill(self, p, r, text, fill, fg="#ffffff"):
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(fg))
        p.setFont(self.f_tag)
        p.drawText(r, Qt.AlignCenter, text)

    def paint_meters(self, p, m, meters):
        """1 ou 2 vumètres (stéréo) côte à côte dans le rectangle m."""
        meters = meters or [None]
        gap = 2 if len(meters) > 1 else 0
        mw = (m.width() - gap * (len(meters) - 1)) / len(meters)
        for k, db in enumerate(meters):
            b = QRectF(m.left() + k * (mw + gap), m.top(), mw, m.height())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#25282c"))
            p.drawRoundedRect(b, 3, 3)
            fr = meter_frac(db)
            if fr > 0:
                h = b.height() * fr
                g = QLinearGradient(b.bottomLeft(), b.topLeft())
                g.setColorAt(0, GREEN)
                g.setColorAt(meter_frac(-12), GREEN)
                g.setColorAt(meter_frac(-6), AMBER)
                g.setColorAt(1, WARN)
                p.setBrush(g)
                p.drawRoundedRect(QRectF(b.left(), b.bottom() - h, b.width(), h), 3, 3)

    def paint_cap(self, p, cx, cy, w):
        cap = QRectF(cx - w / 2, cy - 7, w, 14)
        g = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        g.setColorAt(0, QColor("#9aa1aa"))
        g.setColorAt(1, QColor("#4a4f56"))
        p.setBrush(g)
        p.setPen(QPen(QColor("#22252a"), 1))
        p.drawRoundedRect(cap, 3, 3)
        p.setPen(QPen(QColor(TXT), 1.4))
        p.drawLine(int(cap.left() + 3), int(cy), int(cap.right() - 3), int(cy))

    def paint_compact(self, p, r, c):
        """Case étroite (< COMPACT_W, ex. master réglé à 36 px) : couleur + nom court, vumètres sur toute la largeur
        avec le capuchon du fader par-dessus, valeur en petit (demande de Joseph, 15/10)."""
        col = QColor(c.get("color") or LINE2)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 22), col)
        p.restore()
        dark = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue() > 150
        p.setPen(QColor(PANEL) if dark else QColor("#ffffff"))
        p.setFont(self.f_tag)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 22), Qt.AlignCenter, (c.get("name") or "")[:3])
        y = r.top() + 26
        if c.get("mute"):
            self.pill(p, QRectF(r.left() + 3, y, r.width() - 6, 15), "M", QColor(225, 22, 32))
            y += 18
        bottom = r.bottom() - 20
        m = QRectF(r.left() + 4, y + 2, r.width() - 8, bottom - y - 4)
        self.paint_meters(p, m, c.get("meters"))
        if c.get("pos") is not None:
            self.paint_cap(p, m.center().x(), m.bottom() - m.height() * c["pos"], r.width() - 4)
        p.setPen(QColor(TXT))
        p.setFont(self.f_tag)
        p.drawText(QRectF(r.left() - 2, bottom, r.width() + 4, 18), Qt.AlignCenter, c.get("value", ""))

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
        if c and self.height() < MINI_H:
            self.paint_mini(p, r, c, hot, send)
            return
        if c and r.width() < COMPACT_W:
            p.setPen(QPen(QColor("#ffffff") if hot else QColor(LINE2), 2.0 if hot else 1.0))
            p.setBrush(QColor("#1b1d20") if hot else QColor(PANEL))
            p.drawRoundedRect(r, 6, 6)
            self.paint_compact(p, r, c)
            return
        sel = bool(c and c.get("sel"))
        p.setPen(QPen(QColor("#ffffff") if hot else (QColor(255, 242, 0) if sel else QColor(LINE2)),
                      2.4 if (hot or sel) else 1.0))
        p.setBrush(QColor("#1b1d20") if hot else QColor(PANEL))
        p.drawRoundedRect(r, 10, 10)
        if not c:
            return
        col = QColor(c.get("color") or LINE2)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 32), col)          # bandeau à la couleur du canal
        p.restore()
        dark = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue() > 150   # luminosité perçue
        p.setPen(QColor(PANEL) if dark else QColor("#ffffff"))
        p.setFont(self.f_name)
        p.drawText(QRectF(r.left() + 4, r.top(), r.width() - 8, 32), Qt.AlignCenter, c.get("name", ""))
        # pastilles d'état
        y = r.top() + 37
        tags = []
        if send:
            tags.append(("SEND > " + send, red_gradient(QRectF(0, y, 1, 18)), "#ffffff"))
            if c.get("send_off"):
                tags.append(("OFF", QColor("#5a5f66"), "#ffffff"))
        if c.get("mute"):
            tags.append(("MUTE", QColor(225, 22, 32), "#ffffff"))
        if c.get("solo"):
            tags.append(("SOLO", QColor(242, 182, 59), PANEL))
        if c.get("ph"):
            tags.append(("48V", QColor(209, 52, 59), "#ffffff"))
        x = r.left() + 6
        for text, fill, fg in tags:
            w = min(r.width() - 12, 9 + 7 * len(text)) if not text.startswith("SEND") else r.width() - 12
            if x + w > r.right() - 6:
                x, y = r.left() + 6, y + 21
                w = min(w, r.width() - 12)
            self.pill(p, QRectF(x, y, w, 18), text, fill, fg)
            x += w + 4
        y += 22
        # gain X32 et pan
        info = "  ".join(t for t in (("G " + c["gain"]) if c.get("gain") else "", ("Pan " + c["pan"]) if c.get("pan") else "") if t)
        if info:
            p.setPen(QColor(MUT))
            p.setFont(self.f_tag)
            p.drawText(QRectF(r.left() + 4, y, r.width() - 8, 16), Qt.AlignCenter, info)
        y += 18
        # zone fader + vumètres, valeur en bas
        bottom = r.bottom() - 34
        fx = r.left() + r.width() * 0.32
        top_f, bot_f = y + 6, bottom - 6
        p.setPen(QColor(MUT))
        p.setFont(self.f_scale)
        for mark, lab in ((10, "+10"), (0, "0"), (-10, "-10"), (-20, "-20"), (-40, "-40"), (None, "-inf")):
            yy = bot_f - (bot_f - top_f) * self.fader_frac(mark)
            p.drawText(QRectF(r.left() + 2, yy - 7, fx - r.left() - 12, 14), Qt.AlignRight | Qt.AlignVCenter, lab)
            p.drawLine(int(fx - 8), int(yy), int(fx - 4), int(yy))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#25282c"))
        p.drawRoundedRect(QRectF(fx - 2, top_f, 4, bot_f - top_f), 2, 2)
        pos = c.get("pos")
        if pos is not None:
            self.paint_cap(p, fx, bot_f - (bot_f - top_f) * pos, 22)
        meters = c.get("meters") or [None]
        mw = 11 if len(meters) < 2 else 9
        width = mw * len(meters) + 3 * (len(meters) - 1)
        self.paint_meters(p, QRectF(r.right() - 8 - width, top_f, width, bot_f - top_f), meters)
        p.setPen(QColor(TXT))
        p.setFont(self.f_val)
        p.drawText(QRectF(r.left(), bottom, r.width(), 30), Qt.AlignCenter, c.get("value", ""))

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

    def hit(self, pos):
        for name, r in self.buttons().items():
            if r.contains(pos):
                return ("button", name)
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
# remontent au-dessus), BTN_RECT en pixels de référence 1920x1080 (zone rouge de Joseph, capture du 15/10).
# Ils font PARTIE DU BANDEAU (Joseph) : même apparition, même disparition, même fondu ; pour les atteindre, on tient
# un fader et on appuie sur le bouton à l'écran tactile. Seule fenêtre du rappel qui reçoit les clics, sans prendre
# le focus de la LV1.
BTN_RECT = (38, 862, 54, 134)         # x, y, largeur, hauteur des deux boutons ensemble


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
        self.pid_fn = (lambda: None) if rect_fn else (lambda: lv1_pid(mixer))     # démo : toujours affiché
        self.pid, self.lv1_rect, self.front = None, None, True
        self.rect_fn = rect_fn or (lambda: lv1_rect(mixer))
        self.banner, self.frame = Banner(), Frame()
        self.badge, self.ab, self.ab_key = AbBadge(), None, None
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
        by = min(by, self.recall.cfg["y0"] - bh - 6)           # bandeau grand : les boutons remontent au-dessus
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
        geo = (x, y + round(cfg["y0"] * h / 1080.0), w, round((cfg["y1"] - cfg["y0"]) * h / 1080.0))
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

    def on_msg(self, m):
        if m.get("quit"):
            QApplication.quit()
            return
        if "recall" in m:                            # rappel de pistes : {"cells": [...], "touched": [...], "send"} | null
            self.recall_on = bool(m["recall"])
            if self.recall_on:
                self.recall.set(m["recall"])
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
