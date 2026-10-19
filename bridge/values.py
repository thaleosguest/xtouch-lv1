"""Valeurs LV1 <-> X-Touch : courbe dB <-> course du fader (calibrable, xtouch_courbe_fader.json), niveaux de
vumètre Mackie, échelle du pan de la LV1.

Déplacé de `xtouch_lv1_display.py` (étape 8b du refactor, 19/10/2026)."""
import json
import os
import sys

# Même dossier que HERE du pont (à côté de l'exe une fois compilé, sinon le dossier du projet, parent de bridge/)
HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Seuils dB -> niveau de vumètre Mackie 1..12 (niveau = nombre de seuils atteints).
# Choix provisoire : à ajuster à l'œil sur la X-Touch.
METER_STEPS = [-60.0, -50.0, -42.0, -36.0, -30.0, -24.0, -18.0, -12.0, -9.0, -6.0, -3.0, 0.0]


# Courbe dB -> course du fader (0..1). Provisoire : haut = +10 dB, 0 dB aux 3/4.
FADER_CURVE = [(10.0, 1.0), (5.0, 0.875), (0.0, 0.75), (-5.0, 0.625), (-10.0, 0.5), (-20.0, 0.375),
               (-30.0, 0.25), (-40.0, 0.16), (-50.0, 0.09), (-60.0, 0.04), (-144.0, 0.004)]


def db_to_fader(db):
    """dB -> valeur 14 bits du fader motorisé (0..16383)."""
    if db is None or db <= FADER_CURVE[-1][0]:
        return 0
    if db >= FADER_CURVE[0][0]:
        return 16383
    for (d1, p1), (d2, p2) in zip(FADER_CURVE, FADER_CURVE[1:]):
        if d2 <= db <= d1:
            pos = p2 + (p1 - p2) * (db - d2) / (d1 - d2)
            return int(round(pos * 16383))
    return 0


CURVE_FILE = os.path.join(HERE, "xtouch_courbe_fader.json")
FADER_MIN_DB = -144.0   # « -inf » côté LV1 (plage -144..+10 d'après le module Companion)
INF_POS = 0.004         # course (0..1) en dessous de laquelle le fader vaut -inf (repère ∞ calibrable)


def load_fader_curve():
    """xtouch_courbe_fader.json : [[dB, course 0..1], ...] du haut vers le bas, plus éventuellement
    ["-inf", course] pour la position du repère ∞ (facultatif)."""
    global FADER_CURVE, INF_POS
    try:
        with open(CURVE_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        pts = []
        for d, p in raw:
            if isinstance(d, str) and d.strip().lower() in ("-inf", "inf", "bas"):
                INF_POS = max(0.004, float(p))
            else:
                pts.append((float(d), float(p)))
        pts.sort(key=lambda x: -x[0])
        if pts and pts[-1][0] > FADER_MIN_DB and pts[-1][1] > INF_POS:
            # Sous le repère le plus bas (-60) : descente continue jusqu'à -144 (= -inf LV1) au repère ∞, comme le
            # fader de la LV1. Avant le 15/10 : point à -80 puis saut -80 -> -144 (remarque de Joseph : « on passe
            # de -144 à -78 direct » en montant du bas).
            pts.append((FADER_MIN_DB, INF_POS))
        if len(pts) >= 2:
            FADER_CURVE = pts
            print("  Courbe de fader personnalisée : %d points (xtouch_courbe_fader.json)" % len(pts))
    except (OSError, ValueError, TypeError):
        pass


def fader_to_db(value):
    """Valeur 14 bits du fader (0..16383) -> dB LV1, arrondi à 0,1 dB."""
    pos = max(0.0, min(1.0, value / 16383.0))
    if pos <= INF_POS:
        return FADER_MIN_DB
    top_db, top_pos = FADER_CURVE[0]
    if pos >= top_pos:
        return top_db
    for (d1, p1), (d2, p2) in zip(FADER_CURVE, FADER_CURVE[1:]):
        if p2 <= pos <= p1:
            db = d2 + (d1 - d2) * (pos - p2) / (p1 - p2) if p1 != p2 else d1
            return round(db, 1) + 0.0   # + 0.0 : évite « -0.0 »
    return FADER_MIN_DB


def db_to_level(db):
    if db is None:
        return 0
    return sum(1 for step in METER_STEPS if db >= step)


# Pan côté réseau LV1 : -45 (L45) .. +45 (R45), comme l'écran et la base (bug du 15/10 : envoyé en -1..+1, « tout à
# gauche » donnait L1 sur la LV1 ; ses /Notify/Track/Pan vont bien de -45 à +45). En interne : -1..+1.
# Pan d'envoi aux : même échelle supposée (non vérifié : seule la valeur 0 a été vue).
LV1_PAN_SCALE = 45.0


def pan_label(p):
    """Pan -1..+1 -> « L45 » / « C » / « R12 » (échelle de la LV1), « ? » si inconnu."""
    if p is None:
        return "  ?"
    v = int(round(p * 45))
    return "  C" if v == 0 else ("L%d" % -v if v < 0 else "R%d" % v)
