"""Test : le pont suit le Mixer affiché (demande de Joseph du 18/10 : tout ce qui marche sur Mixer 1 aussi sur Mixer 2).
- ViewFollower : onglet « Mixer 2 » -> vue 1 ; « Channel » / « All » -> la vue reste ; fenêtre MIXER1 détachée au premier
  plan -> vue 0 ; onglet illisible -> rien ; --mixer 2 (fixed) -> jamais changé ; onglet copié dans lv1_tab ;
- la vue est PARTAGÉE : clics (LV1Clicker), boutons (BANK), mode de couche lu pour le bon Mixer ;
- BANK sur Mixer 2 : couches de la vue 1, clic envoyé avec le n° de Mixer 2."""
import sys, time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

st = D.LV1State()
hint = [("Mixer 1", None)]
f = D.ViewFollower(st, None, read=lambda: hint[0])
f.step(); check("Mixer 1", st.view == 0 and st.lv1_tab == "Mixer 1")
hint[0] = ("Mixer 2", None); f.step(); check("Mixer 2", st.view == 1)
hint[0] = ("Channel", None); f.step(); check("Channel garde Mixer 2", st.view == 1 and st.lv1_tab == "Channel")
hint[0] = ("All", None); f.step(); check("All garde Mixer 2", st.view == 1)
hint[0] = (None, 1); f.step(); check("MIXER1 détaché devant", st.view == 0 and st.lv1_tab == "All")
hint[0] = (None, None); f.step(); check("illisible : rien", st.view == 0)
st2 = D.LV1State(); st2.view = 1
g = D.ViewFollower(st2, 1, read=lambda: ("Mixer 1", None)); g.step()
check("--mixer 2 imposé", st2.view == 1 and st2.lv1_tab == "Mixer 1")

# vue partagée : BANK sur Mixer 2 -> couches de la vue 1 + clic avec Mixer 2
st = D.LV1State()
lay = [("Ch 1-16", [(0, i) for i in range(16)]), ("Ch 17-32", [(0, 16 + i) for i in range(16)])]
st.last_set = {0: lay, 1: lay}
st.current = {0: 0, 1: 0}
clicks, modes = [], []
clk = D.LV1Clicker(st, 0, click_layer=lambda k, m, **kw: (clicks.append((k, m)), (True, None))[1],
                   click_strip=lambda *a, **k: (True, None), jog=lambda n: (True, None),
                   click_mode=lambda *a: (modes.append(a), (True, None))[1], click_all=lambda *a: (True, None))
b = D.ButtonControl(st, None, write=False, page=0)
b.lv1 = clk
clk.WAIT_LAYER = 0.05
clk.start()
st.view = 1                                         # l'onglet Mixer 2 est affiché
b.on_midi(1, 0x90, D.NOTE_BANK_RIGHT, 127, 0, [], None)
st.n_inputs = 80
b.on_midi(1, 0x90, D.NOTE_USER, 127, 0, [], None)
time.sleep(0.4)
check("BANK sur Mixer 2", st.local.get(1) == 1 and 0 not in st.local and clicks == [(1, 2)])
check("mode sur Mixer 2", modes == [("custom", 80, 2)])
check("vue partagée", b.page == clk.page == 1)
w = D.LayerModeWatcher(st, 1, read=lambda: (5, 80), stamp=lambda: 7, tab=None, spill=lambda: None)
w.step(); st.view = 0
reads = []
w.read = lambda: (reads.append(1), (4, 80))[1]
w.step()
check("mode relu pour l'autre Mixer", reads == [1] and st.layer_mode.get(1) == 5 and st.layer_mode.get(0) == 4)
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
