"""Textes et codes affichés par la X-Touch : gain, valeur de fader, 7 segments, timecode / heure, couleur d'écran.

Fonctions pures (rien n'est envoyé ici). Déplacées telles quelles de `xtouch_lv1_display.py` (étape 6 du refactor,
19/10/2026), qui les réexporte.
"""
import colorsys
import unicodedata

from surface.notes import XT


def ascii7(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return t.strip()


def fader_text(db):
    if db is None:
        return ""
    if db <= -120:
        return "  -inf"
    return ("%+.1f" % db).rjust(6)


def rgb_to_xtouch(rgb):
    """RVB 0..1 -> couleur X-Touch la plus proche, par la teinte."""
    if not rgb:
        return XT["blanc"]
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.25 or v < 0.15:
        return XT["blanc"]
    deg = h * 360.0
    if deg < 20 or deg >= 330:
        return XT["rouge"]
    if deg < 75:
        return XT["jaune"]
    if deg < 160:
        return XT["vert"]
    if deg < 200:
        return XT["cyan"]
    if deg < 260:
        return XT["bleu"]
    return XT["violet"]


SIDE_NAMES = {0: "L", 1: "R"}


def gain_label(gains, side=0):
    """Texte (7 car. max) du gain d'une tranche : mono « +12.0 » ; stéréo : côté réglé « L+12.0 » / « R+11.5 »."""
    if not gains or any(g is None for g in gains):
        return "  -"
    if len(gains) == 2:
        return "%s%+.1f" % ("LR"[side], gains[side])
    return "%+.1f" % gains[0]


# Codes : ASCII 0x40-0x5F (@, A-Z…) -> valeur - 0x40 ; ASCII 0x20-0x3F (espace, chiffres, -) -> tel quel ;
# + 0x40 = point décimal allumé. Choix de Joseph (option C) : canal sélectionné + son gain, fader LR.


def seg_codes(text, width):
    """Texte -> `width` codes 7 segments (de gauche à droite), points fusionnés dans le caractère précédent,
    aligné à droite. Caractères non affichables (+, minuscules…) : convertis ou remplacés par un espace."""
    out = []
    for c in text.upper():
        if c == "." and out:
            out[-1] |= 0x40
            continue
        o = ord(c)
        if 0x40 <= o <= 0x5F:
            out.append(o - 0x40)
        elif 0x20 <= o <= 0x3F and c != "+":
            out.append(o)
        else:
            out.append(0x20)
    out = out[-width:]
    return [0x20] * (width - len(out)) + out


def time_display(seconds, clock):
    """Afficheur 7 segments hors mode sends (demande de Joseph du 16/10/2026, remplace le canal sélectionné / gain / LR :
    « assez d'indices avec l'écran ») : (2 car. assignment, 10 car. timecode), groupes 3-2-2-3 de la X-Touch.
    seconds = position de REAPER LV1 (/time) -> heures.minutes.secondes.millièmes ; None -> heure du PC (`clock`,
    struct_time : la même que l'horloge de la LV1, qui tourne sur ce PC) en heures.minutes.secondes."""
    if seconds is not None:
        ms = int(round(max(0.0, seconds) * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        text = "%3d.%02d.%02d.%03d" % (h % 1000, m, s, ms)
    else:
        text = "%3d.%02d.%02d   " % (clock.tm_hour, clock.tm_min, clock.tm_sec)
    return seg_codes("", 2), seg_codes(text, 10)
