"""Test étape 3 (10/11/2026, disposition « comme le contrôleur LV1 ») : modes des encodeurs PAN (départ) -> TRACK GAIN
(préampli X32, sinon trim) -> TRIM -> PAN ; ligne du bas = encodeur, niveau du fader pendant le toucher ; messages sur
toute la largeur (mode, sends, USER, SHIFT) ; noms raccourcis ; --essai-vumetre.

    py tests/test_ecrans.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_probe as X
import xtouch_lv1_display as D
from surface.banner import apply_banner, banner_cells, compact, pack_words, shift_message

ok, why = True, []


def check(name, cond):
    global ok
    print(("ok    " if cond else "ÉCHEC ") + name)
    if not cond:
        ok = False
        why.append(name)


# ── noms raccourcis et cases de message
check("fit7", [D.fit7(n) for n in ("Kick In", "Lead Vocal", "Overhead L", "Tom Floor 2", "Out_CtrlRoom")]
      == ["Kick In", "LeadVcl", "OverhdL", "TomFlr2", "OtCtrlR"])
check("short_name garde In / Grp", D.short_name("Channel 12", 0, 11) == "In 12" and D.short_name("Group 3", 1, 2) == "Grp 3")
check("cases", [c.strip() for c in banner_cells("SENDS", "TO", "Mon 16")] == ["SENDS", "TO", "Mon 16"]
      and pack_words("ABCDEFGHIJ") == ["ABCDEFG", "HIJ"] and pack_words("Drums & Bass") == ["Drums &", "Bass"])
check("compact", compact("Ch 65-80") == "Ch65-80" and compact("Drums & Bass") == "Drums & Bass")
row = apply_banner(["a"] * 16, banner_cells("LAYER 2", "Ch17-32"))
check("message centré, reste vidé", row[7] == "LAYER 2" and row[8] == "Ch17-32" and row.count("") == 14)
check("SHIFT : A / B / ?", [c.strip() for c in shift_message(False)][-1] == "ON A"
      and [c.strip() for c in shift_message(True)][-1] == "ON B" and [c.strip() for c in shift_message(None)][-1] == "ON ?")


# ── modes des encodeurs
class FakeLink:
    def preamps(self, e): return [32] if e == (0, 0) else []
    def gain(self, e, side=None): return 10.0 if e == (0, 0) else None
    def gains_of(self, e): return [10.0] if e == (0, 0) else []
    def phantom_on(self, e, side=None): return False
    def nudge(self, e, d, side=None): return 10.0 + d


class FakeLV1:
    def __init__(self): self.sent = []
    def send(self, a, args): self.sent.append((a, [v for _, v in args]))


st = D.LV1State()
lv1 = FakeLV1()
g = D.GainControl(st, FakeLink(), write=True, lv1=lv1)
check("PAN au départ", g.mode_name() == "pan" and g.pan_mode)


def press(note):
    g.on_midi(1, 0x90, note, 127, 0.0, [], None)
    g.on_midi(1, 0x90, note, 0, 0.0, [], None)


press(D.NOTE_TRACK)
check("TRACK -> GAIN", g.mode_name() == "gain" and not g.pan_mode)
entries = [(0, 0), (0, 1)] + [None] * 14
g.on_midi(0, 0xB0, D.CC_VPOT + 1, 0x02, 0.0, entries, None)          # In 2 : pas de préampli -> trim +1.0
check("GAIN sans préampli X32 = trim", lv1.sent == [("/SetTrackTrim", [0, 1, 0, 1.0])])
bot = [""] * 16
rings, recs = g.frame(entries, bot)
check("GAIN : affichage X32 / trim", bot[0].strip().startswith("+10") and bot[1] == "T+1.0" and rings[1] == 0x16)
lv1.sent.clear()
g.on_midi(0, 0x90, D.NOTE_VPOT_PUSH + 1, 127, 0.0, entries, None)     # appui en GAIN sur un trim : pas de phase
check("GAIN : appui sans phase", lv1.sent == [])
press(D.NOTE_TRACK)
check("TRACK -> TRIM", g.mode_name() == "trim")
press(D.NOTE_TRACK)
check("TRACK -> PAN", g.mode_name() == "pan")
press(D.NOTE_PAN)
check("PAN reste PAN", g.mode_name() == "pan")
g2 = D.GainControl(st, None, write=False)
g2.on_midi(1, 0x90, D.NOTE_TRACK, 127, 0.0, [], None)
check("sans Gain Recall : TRACK -> TRIM", g2.mode_name() == "trim")


# ── boucle d'affichage : ligne du bas, messages, essai des vumètres
class Midi:
    def __init__(self): self.log = []
    def short(self, h, st, d1, d2=0): self.log.append(("C", h, st, d1, d2))
    def long(self, h, data): self.log.append(("S", h, bytes(data)))


class FakeFaders:
    def __init__(self): self.t = []
    def touch_display(self, now): return list(self.t)


def app_de_test(essai=False):
    midi = Midi()
    state = D.LV1State()
    state.connected = True
    state.tracks[(0, 0)] = {"name": "Kick", "fader": -6.0, "pan": 0.0}
    xt = D.Surface(midi, [("Extender", X.ID_EXT, "ext"), ("X-Touch", X.ID_MAIN, "main")])
    gain = D.GainControl(state, None, write=False, lv1=None)

    class A: essai_vumetre = essai
    app = D.App(A())
    app.state, app.xt, app.gain = state, xt, gain
    app.sends = D.SendControl(state, None, write=False, gain=gain)
    app.buttons = D.ButtonControl(state, None, write=False, page=0)
    app.faders = FakeFaders()
    app.master_target = (3, 0)
    app.entries = [None] * xt.strips
    app.shown_view = state.view
    state.last_set = {0: [("Ch 1-16", [(0, i) for i in range(16)])]}
    state.current = {0: 0}
    return app, midi


def lcd(midi, unit, row):
    """Dernier texte envoyé à une ligne d'écran : unit « ext » / « main », row 0 (haut) / 1 (bas)."""
    for kind, h, *rest in reversed(midi.log):
        if kind == "S" and h == unit and rest[0][5] == 0x12 and rest[0][6] == (0 if row == 0 else 56):
            t = rest[0][7:-1].decode()
            return [t[i:i + 7] for i in range(0, 56, 7)]
    return None


app, midi = app_de_test()
t = 1000.0
app.tick_render(t, ())
app.tick_render(t + 2.0, ())                       # après le message de couche
check("ligne du bas = pan", lcd(midi, "ext", 1)[0].strip() == "C")
app.faders.t = [0]
app.tick_render(t + 2.1, ())
check("fader touché : niveau en dB", "-6" in lcd(midi, "ext", 1)[0])
app.faders.t = []
app.tick_render(t + 2.8, ())
check("encore 1 s après", "-6" in lcd(midi, "ext", 1)[0])
app.tick_render(t + 3.3, ())
check("puis le pan revient", lcd(midi, "ext", 1)[0].strip() == "C")
app.gain.on_midi(1, 0x90, D.NOTE_TRACK, 127, t, [], None)
app.tick_render(t + 3.4, ())
both = lcd(midi, "ext", 1) + lcd(midi, "main", 1)
check("message ENCODER TRIM", "ENCODER" in both and any("TRIM" in c for c in both))
app.tick_render(t + 5.5, ())
check("message fini", "ENCODER" not in lcd(midi, "ext", 1) + lcd(midi, "main", 1))
app.sends.on_midi(1, 0x90, D.NOTE_SHIFT, 127, t, [], None)
app.tick_render(t + 5.6, ())
both = lcd(midi, "ext", 1) + lcd(midi, "main", 1)
check("SHIFT tenu : message", any("SHIFT" in c for c in both) and any("ON ?" in c for c in both))
app.sends.on_midi(1, 0x90, D.NOTE_SHIFT, 0, t, [], None)
app.tick_render(t + 5.7, ())
check("SHIFT relâché : fini", not any("SHIFT" in c for c in lcd(midi, "ext", 1) + lcd(midi, "main", 1)))
app.sends.on_midi(1, 0x90, D.NOTE_USER, 127, t, [], None)
app.tick_render(t + 5.8, ())
check("message USER KEYS", any("USER" in c for c in lcd(midi, "ext", 1) + lcd(midi, "main", 1)))

app, midi = app_de_test(essai=True)
for k, want in enumerate((12, 13, 14, 6, 15, 0)):
    app.tick_render(t + k * D.VU_TEST_STEP + 0.1, ())
    meters = [x for x in midi.log if x[0] == "C" and x[1] == "main" and x[2] == 0xD0 and x[3] >> 4 == 0]
    check("essai vumètre étape %d : valeur %d" % (k + 1, want), meters and meters[-1][3] & 0x0F == want)
check("essai vumètre : écran", lcd(midi, "main", 0)[0] == "TEST VU")

# ── témoin de saturation : 0 dBFS -> valeur 14 (LED rouge), tenue 1 s
check("niveaux", D.db_to_level(-70) == 0 and D.db_to_level(-3) == 11 and D.db_to_level(0.0) == 14 and D.db_to_level(3) == 14)
app, midi = app_de_test()
def meter_main0():
    m = [x for x in midi.log if x[0] == "C" and x[1] == "ext" and x[2] == 0xD0 and x[3] >> 4 == 0]
    return m[-1][3] & 0x0F if m else None
import types
app.state.meter = types.MethodType(lambda self, g, c, side: 1.0 if (g, c) == (0, 0) else None, app.state)
app.tick_render(t, ())
check("0 dBFS : LED rouge", meter_main0() == 14)
app.state.meter = types.MethodType(lambda self, g, c, side: -20.0 if (g, c) == (0, 0) else None, app.state)
app.tick_render(t + 0.5, ())
check("tenue 1 s", meter_main0() == 14)
app.tick_render(t + 1.2, ())
check("puis le niveau revient", meter_main0() == D.db_to_level(-20.0))

# ── saturation à l'ENTRÉE : préampli X32 (vumètres de Gain Recall), le vumètre LV1 étant post-fader (Joseph, 10/11)
import xgr_link
lk = xgr_link.GainRecallLink(opener=lambda *a: {})
lk.ok = True
lk.idx_of_exp, lk.sources = {17: 32}, {1: [17]}
check("vumètres éteints : à allumer (1re fois)", lk.apply_meters({"on": False, "live": False, "v": []}, now=100.0) == "first")
check("pas deux fois en 30 s", lk.apply_meters({"on": False}, now=110.0) is False
      and lk.apply_meters({"on": False}, now=131.0) is True)
check("réponse sans « on » (autre serveur) : rien", lk.apply_meters({}, now=200.0) is False)
v = [None] * 64
v[32] = -0.2
lk.apply_meters({"on": True, "live": True, "v": v}, now=300.0)
check("niveau du préampli de In 1", lk.input_level((0, 0), now=300.5) == -0.2 and lk.input_level((0, 1), now=300.5) is None)
check("niveau trop vieux : inconnu", lk.input_level((0, 0), now=302.0) is None)

app, midi = app_de_test()
app.state.meter = types.MethodType(lambda self, g, c, side: -40.0 if (g, c) == (0, 0) else None, app.state)


class FakeX:
    level = -0.2
    def input_level(self, e, now=None): return self.level if e == (0, 0) else None
    def gain(self, *a): return None
    def preamps(self, e): return []
    def phantom_on(self, *a): return False


app.xlink = FakeX()
app.tick_render(t, ())
check("préampli saturé, fader bas : LED rouge", meter_main0() == 14)
app.xlink.level = -12.0
app.tick_render(t + 0.5, ())
check("tenue 1 s", meter_main0() == 14)
app.tick_render(t + 1.2, ())
check("puis le vumètre LV1 revient", meter_main0() == D.db_to_level(-40.0))

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
