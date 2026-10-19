"""Test : trim et phase de la LV1 sur les encodeurs (demande de Joseph du 19/10/2026, commandes de la capture MyFOH).
- TRACK : normal -> gain X32 -> trim LV1 -> normal ; sans Gain Recall : normal -> trim -> normal ; PAN sort du trim ;
- trim : encodeur +2 crans -> /SetTrackTrim g ch 0 f (+1.0 dB) ; canal stéréo -> 3e argument 1 ; « T+1.0 » en bas ;
- appui encodeur en trim -> /SetTrackPhaseState g ch stéréo 0|1 ; LED Rec = phase ; Rec tenu en trim : pas de 48 V ;
- /Notify/TrackTrim et /Notify/PhaseState de la LV1 mettent l'état à jour ;
- en sends on fader, le trim garde les encodeurs (pas le pan d'envoi).

    py tests/test_trim_phase.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


class LV1:
    def __init__(self):
        self.sent = []

    def send(self, address, args=()):
        self.sent.append((address, [a[1] for a in args]))


class XGR:                                    # faux X/M32 Gain Recall (présent)
    def preamps(self, e): return []
    def gain(self, e, side=None): return None
    def gains_of(self, e): return []
    def phantom_on(self, e, side=None): return True
    def set_phantom(self, *a): raise AssertionError("48 V envoyé en trim")


TRACK = (0x90, D.NOTE_TRACK, 127)
st = D.LV1State()
st.track(0, 0)["stereo"] = True               # « P170 ST »
st.track(0, 1)["stereo"] = False
entries = [(0, 0), (0, 1)] + [None] * 14
lv1 = LV1()
g = D.GainControl(st, XGR(), write=True, lv1=lv1)


def midi(st_, d1, d2, t=0.0, unit=0):
    return g.on_midi(unit, st_, d1, d2, t, entries, None)


# cycle de TRACK avec Gain Recall
midi(*TRACK); check("1er appui : gain", g.mode and not g.trim_mode)
midi(*TRACK); check("2e appui : trim", g.trim_mode and not g.mode)
midi(*TRACK); check("3e appui : normal", not g.mode and not g.trim_mode)
g2 = D.GainControl(st, None, write=True, lv1=lv1)
g2.on_midi(0, *TRACK, 0.0, entries, None)
check("sans Gain Recall : directement trim", g2.trim_mode and not g2.mode)
g2.on_midi(0, *TRACK, 0.0, entries, None)
check("sans Gain Recall : puis normal", not g2.trim_mode)

# trim : encodeur 2 (mono) +2 crans, encodeur 1 (stéréo) -1 cran
midi(*TRACK); midi(*TRACK)
midi(0xB0, D.CC_VPOT + 1, 0x02)
midi(0xB0, D.CC_VPOT + 0, 0x41)
check("mono : /SetTrackTrim 0 1 0 +1.0", lv1.sent[0] == ("/SetTrackTrim", [0, 1, 0, 1.0]))
check("stéréo : 3e argument 1, -0.5", lv1.sent[1] == ("/SetTrackTrim", [0, 0, 1, -0.5]))
bot = [""] * 16
rings, recs = g.frame(entries, bot)
check("ligne du bas « T+1.0 »", bot[1] == "T+1.0" and bot[0] == "T-0.5")
check("couronne depuis le centre", rings[1] & 0xF0 == 0x10)

# retour de la LV1
D.handle(st, "/Notify/TrackTrim", [("i", 0), ("i", 1), ("i", 0), ("f", 3.4), ("i", 1)])
g.frame(entries, bot)
check("/Notify/TrackTrim pris en compte", bot[1] == "T+3.4")

# phase : appui encodeur 2
midi(0x90, D.NOTE_VPOT_PUSH + 1, 127)
check("/SetTrackPhaseState 0 1 0 1", lv1.sent[-1] == ("/SetTrackPhaseState", [0, 1, 0, 1]))
rings, recs = g.frame(entries, bot)
check("LED Rec = phase inversée", recs[1] and not recs[0])
D.handle(st, "/Notify/PhaseState", [("i", 0), ("i", 1), ("i", 0), ("i", 0), ("i", 1)])
rings, recs = g.frame(entries, bot)
check("/Notify/PhaseState pris en compte", not recs[1])

# Rec tenu en trim : pas de 48 V (XGR.set_phantom lèverait une erreur)
midi(0x90, D.NOTE_REC + 1, 127, t=0.0)
midi(0x90, D.NOTE_REC + 1, 0, t=2.0)

# sends on fader + trim : les encodeurs restent au trim
sends = D.SendControl(st, LV1(), write=True, gain=g)
sends.aux = 0
n = len(lv1.sent)
took = sends.on_midi(0, 0xB0, D.CC_VPOT + 1, 0x01, 0.0, entries, None)
check("sends : encodeur laissé au trim", not took)

# PAN sort du trim
midi(0x90, D.NOTE_PAN, 127)
check("PAN : sort du trim", g.pan_mode and not g.trim_mode)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
