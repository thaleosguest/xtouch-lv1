"""Test : DISPLAY bascule le premier plan LV1 <-> Reaper ; SAVE selon la fenêtre active (Reaper : Save as ;
LV1 : User Key « Store » ; autre : rien). Fenêtres simulées (fenetres.front_app / bring remplacés)."""
import sys, time
sys.path.insert(0, sys.argv[1])
import fenetres
import xtouch_lv1_display as D

FRONT = ["lv1"]
BROUGHT = []
fenetres.front_app = lambda mixer=1: FRONT[0]
fenetres.bring = lambda app, mixer=1: BROUGHT.append(app) or True


class Link:
    def __init__(self): self.sent = []
    def send(self, a, args): self.sent.append((a, [v for _t, v in args]))


class Reaper:
    def __init__(self): self.acts = []
    def action(self, n): self.acts.append(n)


class Surf:
    master_unit = 1


st = D.LV1State()
st.user_keys = {3: ("Store", "Scenes: Store Next", True), 15: ("FlipAB", "Flip AB Input channel", True)}
link, rp = Link(), Reaper()
ap = D.AppControl(st, link, rp)
press = lambda note: ap.on_midi(1, 0x90, note, 127, time.time(), [], Surf())

press(D.NOTE_DISPLAY); time.sleep(0.1)                      # LV1 devant -> Reaper
FRONT[0] = "reaper"; press(D.NOTE_DISPLAY); time.sleep(0.1)  # Reaper devant -> LV1
press(D.NOTE_SAVE)                                          # Reaper devant -> Save as
FRONT[0] = "lv1"; press(D.NOTE_SAVE)                        # LV1 devant -> User Key 4 (store)
FRONT[0] = "autre"; press(D.NOTE_SAVE)                      # autre : rien
print("premier plan demandé :", BROUGHT, "| Reaper :", rp.acts, "| LV1 :", link.sent)
ok = BROUGHT == ["reaper", "lv1"] and rp.acts == [D.ACT_REAPER_SAVE_AS]
ok = ok and link.sent == [("/Set/UserKey", [3, True]), ("/Set/UserKey", [3, False])]
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
