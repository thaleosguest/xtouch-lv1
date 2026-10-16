"""Test : touches View de la X-Touch -> boutons de mode de couche de la LV1 (demande de Joseph du 16/10).
- lv1_db.layer_mode sur une fausse base (surface 2 / 3, propriété 12 ; config_info) ;
- LayerModeWatcher : relit seulement quand la base change ;
- voyants : INPUTS = Input ou Factory, BUSES = Mix, USER = Custom, GROUP = Spill, GLOBAL VIEW = onglet All ;
- touches : INPUTS = input en 80 canaux, factory sinon ; BUSES ignoré hors 80 ; USER = custom ; GROUP = spill ; GLOBAL VIEW = onglet All ;
- SMPTE : bascule timecode REAPER / heure ; garde-fou de la rangée Custom / Spill (mode_row_why) ;
- garde-fou des cases de couche : bord gauche clair (gris, bleu, violet en Custom) ;
- LV1Clicker : clic du mode avec le nombre de canaux et le n° de Mixer ; lv1_clic refuse un bouton absent."""
import os, sqlite3, sys, tempfile, time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
import lv1_db, lv1_clic

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

d = tempfile.mkdtemp(prefix="modes_")
db = os.path.join(d, "CurrentLV1.dat")
c = sqlite3.connect(db)
c.execute("create table surface_property_int (surface int, property int, value int)")
c.execute("create table config_info (track_type int, num_tracks int)")
c.executemany("insert into surface_property_int values (?, ?, ?)", [(2, 12, 5), (3, 12, 1), (2, 14, 0)])
c.executemany("insert into config_info values (?, ?)", [(0, 80), (1, 16)])
c.commit(); c.close()
check("base Mixer 1", lv1_db.layer_mode(1, db) == (5, 80))
check("base Mixer 2", lv1_db.layer_mode(2, db) == (1, 80))

st = D.LV1State()
reads, stamp = [], [1]
w = D.LayerModeWatcher(st, 0, read=lambda: (reads.append(1), (4, 80))[1], stamp=lambda: stamp[0], tab=lambda: "All")
w.step(); w.step()
check("lu une fois", len(reads) == 1 and st.layer_mode.get(0) == 4 and st.n_inputs == 80 and st.lv1_tab == "All")
stamp[0] = 2; w.step()
check("relu au changement", len(reads) == 2)

L = D.view_leds
check("voyants", L(4)[D.NOTE_INPUTS] and L(0)[D.NOTE_INPUTS] and L(5)[D.NOTE_BUSES] and L(1)[D.NOTE_USER]
      and L(3)[D.NOTE_GROUP] and L(4, "All")[D.NOTE_GLOBAL_VIEW] and not L(3)[D.NOTE_GLOBAL_VIEW]
      and not any(L(None).values())
      and sum(L(5, "Mixer 1").values()) == 1)

class FakeClicker:
    def __init__(self): self.modes = []
    def mode(self, name): self.modes.append(name)
    def all_tab(self): self.modes.append("all")
b = D.ButtonControl(st, None, write=False)
b.lv1 = FakeClicker()
def press(note):
    b.on_midi(1, 0x90, note, 0x7F, 0, [], None); b.on_midi(1, 0x90, note, 0, 0, [], None)
for n in (D.NOTE_INPUTS, D.NOTE_BUSES, D.NOTE_USER, D.NOTE_GROUP, D.NOTE_GLOBAL_VIEW):
    press(n)
check("80 canaux", b.lv1.modes == ["input", "mix", "custom", "spill", "all"])
b.lv1.modes.clear(); st.n_inputs = 64
press(D.NOTE_INPUTS); press(D.NOTE_BUSES)
check("64 canaux", b.lv1.modes == ["factory"])
check("SMPTE départ", b.reaper_tc is True)
press(D.NOTE_SMPTE)
check("SMPTE -> heure", b.reaper_tc is False)
press(D.NOTE_SMPTE)
check("SMPTE -> REAPER", b.reaper_tc is True)

calls = []
clk = D.LV1Clicker(st, 1, click_layer=lambda *a, **k: (True, None), click_strip=lambda *a, **k: (True, None),
                   jog=lambda n: (True, None), click_mode=lambda *a: (calls.append(a), (True, None))[1],
                   click_all=lambda *a: (calls.append(("all",) + a), (True, None))[1])
clk.start()
clk.mode("custom"); clk.all_tab()
for _ in range(50):
    if len(calls) >= 2: break
    time.sleep(0.02)
check("clic du mode + onglet", calls == [("custom", 64, 2), ("all", 2)])
# garde-fou : rangée Custom / Spill avec du texte clair (capture du 16/10 : 8 à 11 points) ; fond seul -> refus
text = lambda x, y: (201, 201, 201) if (x // 2) % 3 == 0 else (17, 17, 17)
check("rangée vue", lv1_clic.mode_row_why(text) is None)
check("rangée absente", lv1_clic.mode_row_why(lambda x, y: (17, 17, 17)) is not None)
edge = lambda x, y: (160, 160, 160) if x == 1784 else (71, 71, 71)           # contour gris d'une case inactive
check("case de couche", lv1_clic.layer_edge_why(edge, 3) is None
      and lv1_clic.layer_edge_why(lambda x, y: (71, 71, 71), 3) is not None
      and lv1_clic.layer_edge_why(lambda x, y: (140, 81, 192) if x >= 1784 else (71, 71, 71), 0) is None)   # Custom
check("bouton absent", lv1_clic.click_mode("mix", 64)[0] is False and lv1_clic.click_mode("factory", 80)[0] is False)
check("positions", lv1_clic.MODE_BUTTONS["factory"] == (1847, 442) and lv1_clic.MODE_BUTTONS["spill"] == (1881, 479))

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
