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


class Bus(QObject):
    msg = Signal(dict)


class Overlay:
    def __init__(self, mixer=1, rect_fn=None):
        self.rect_fn = rect_fn or (lambda: lv1_rect(mixer))
        self.banner, self.frame = Banner(), Frame()
        self.badge, self.ab, self.ab_key = AbBadge(), None, None
        self.state = None            # (text, sub, color) voulu
        self.since = 0.0
        self.rect, self.rect_t = None, 0.0
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)

    def tick_badge(self, now):
        if not self.ab or self.ab_key is None or not self.rect:
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
            self.rect, self.rect_t = self.rect_fn(), now
        self.tick_badge(now)
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
