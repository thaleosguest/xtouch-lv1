"""Test : F1..F8 = couches 1..8 en accès direct (comme le contrôleur LV1, Joseph 10/11/2026), LED = couche affichée ;
AUDIO TRACKS = mode Custom ; USER = les Select deviennent les User Keys (noms en ligne du haut, SEND en sort) ;
FLIP = sends on fader comme SEND, SHIFT + FLIP = Flip A/B (étape 2).

    py tests/test_couches_fkeys.py .
"""
import sys
import time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []


def check(name, cond):
    global ok
    print(("ok    " if cond else "ÉCHEC ") + name)
    if not cond:
        ok = False
        why.append(name)


def press(ctl, unit, note):
    r = ctl.on_midi(unit, 0x90, note, 127, 0, [], None)
    ctl.on_midi(unit, 0x90, note, 0, 0, [], None)
    return r


# ── F1..F8 -> couches
st = D.LV1State()
lay = [("Ch 1-16", [(0, i) for i in range(16)]), ("Ch 17-32", [(0, 16 + i) for i in range(16)]),
       (" ", [None] * 16), ("Ch 33-48", [(0, 32 + i) for i in range(16)])]
st.last_set = {0: lay}
st.current = {0: 0}
held = [False]
layers = []


class FakeClicker:
    def layer(self, k): layers.append(k)


b = D.ButtonControl(st, None, write=False, page=0, busy=lambda: held[0])
b.lv1 = FakeClicker()
F = D.NOTE_F1
check("F2 pris", press(b, 1, F + 1) is True)
check("F2 -> couche 2", st.shown_layer(0) == 1 and layers == [1])
check("LED F2 seule", D.layer_leds(st.shown_layer(0)) == [False, True] + [False] * 6)
press(b, 1, F + 2)
check("F3 (couche vide) : inchangé", st.shown_layer(0) == 1 and layers == [1])
press(b, 1, F + 7)
check("F8 (couche absente) : inchangé", st.shown_layer(0) == 1 and layers == [1])
press(b, 1, F + 3)
check("F4 -> couche 4", st.shown_layer(0) == 3 and layers == [1, 3])
check("entrées de la couche 4", st.layer_entries(0)[1][0] == (0, 32))
held[0] = True
press(b, 1, F)
check("F1 ignoré fader tenu", st.shown_layer(0) == 3 and layers == [1, 3])
held[0] = False
press(b, 1, F)
check("F1 -> couche 1", st.shown_layer(0) == 0 and layers == [1, 3, 0])
check("aucune couche connue : LED éteintes", D.layer_leds(None) == [False] * 8)

# ── USER : Select = User Keys
sent = []


class FakeLink:
    def send(self, a, args): sent.append((a, [v for _, v in args]))


st.user_keys = {0: ("TB", "Talkback", True), 1: ("", "User 2", False), 9: ("Reverb", "Mute Group 1", True)}
s = D.SendControl(st, FakeLink(), write=True)
check("Select hors mode USER : pas pris", s.on_midi(0, 0x90, D.NOTE_SELECT, 127, 0, [], None) is False)
press(s, 1, D.NOTE_USER)
check("USER -> mode User Keys", s.user_mode)
press(s, 1, D.NOTE_SELECT + 1)          # tranche 10 (X-Touch) -> User Key 10
check("Select 10 -> User Key 10", sent == [("/Set/UserKey", [9, True]), ("/Set/UserKey", [9, False])])
n = 16
top, bot, cols, fads = [""] * n, [""] * n, [0] * n, [0] * n
st.last_leds = ([False] * n, [False] * n, [True] + [False] * (n - 1))
mutes, solos, selects = s.frame([(0, i) for i in range(n)], top, bot, cols, fads, {})
check("noms des User Keys en haut", top[0] == "TB" and top[1] == "-" and top[9] == "Reverb" and top[2] == "-")
check("LED Select = Flip Sends seulement", not any(selects))
press(s, 1, D.NOTE_SEND)
check("SEND : sort du mode USER", not s.user_mode and s.picking)
press(s, 1, D.NOTE_USER)
check("USER pendant le choix de l'aux : choix abandonné", s.user_mode and not s.picking)
press(s, 1, D.NOTE_USER)
check("USER à nouveau : Select = sélection", not s.user_mode)

# ── FLIP = sends on fader (comme SEND) ; SHIFT + FLIP = Flip A/B (ButtonControl)
st.aux_tracks = [(2, k, "Fx %d" % (k + 1)) for k in range(8)] + [(25, k, "Mon %d" % (k + 1)) for k in range(16)]
check("FLIP pris par les sends", press(s, 1, D.NOTE_FLIP) is True and s.picking and not s.user_mode)
check("LED FLIP / SEND clignote au choix", {s.mode_led(0.0), s.mode_led(0.4)} == {True, False})
s.on_midi(0, 0x90, D.NOTE_SELECT + 2, 127, 0, [], None)
check("Select 3 -> aux 2", s.aux == 2 and not s.picking and s.mode_led(0.2))
press(s, 1, D.NOTE_FLIP)
check("FLIP à nouveau : retour", s.aux is None and not s.picking)
sent.clear()
st.user_keys[15] = ("FlipAB", "Flip AB Input channel", True)
b2 = D.ButtonControl(st, FakeLink(), write=True, page=0)
s.on_midi(1, 0x90, D.NOTE_SHIFT, 127, 0, [], None)
check("SHIFT tenu", s.shift)
taken = s.on_midi(1, 0x90, D.NOTE_FLIP, 127, 0, [], None)
check("SHIFT + FLIP : pas pour les sends", taken is False and not s.picking)
b2.on_midi(1, 0x90, D.NOTE_FLIP, 127, 0, [], None)
check("SHIFT + FLIP -> User Key 16", sent == [("/Set/UserKey", [15, True]), ("/Set/UserKey", [15, False])])
s.on_midi(1, 0x90, D.NOTE_SHIFT, 0, 0, [], None)
check("SHIFT relâché", not s.shift)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
