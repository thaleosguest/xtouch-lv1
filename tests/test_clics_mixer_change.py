"""Test : clics en attente abandonnés quand le Mixer change (étape 10, correctif 2, 19/10/2026).
Un clic demandé sur Mixer 1 et encore dans la file au passage sur Mixer 2 partait sur Mixer 2 (mauvais endroit).
- couche, mode, sélection, onglet All, jog demandés sur Mixer 1, puis vue -> Mixer 2 : rien n'est cliqué, journal
  « annulé : Mixer changé » pour chacun ;
- demandes faites sur Mixer 2 ensuite : cliquées sur Mixer 2 ;
- deux sélections de Mixers différents ne sont pas fusionnées (la 1re est abandonnée, la 2e part).

    py tests/test_clics_mixer_change.py .
"""
import sys, time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

MARKS = []
class J:
    def write(self, *a): pass
    def mark(self, text): MARKS.append(text)
D.JOURNAL.current = J()

clics = []
st = D.LV1State()
st.view = 0
st.n_inputs = 64
TRACK = (0, 3)
for v in (0, 1):                                      # même jeu de couches sur les deux Mixers, couche 0 affichée
    st.last_set[v] = [("Ch 1-16", [(0, i) for i in range(16)])]
    st.current[v] = 0
clk = D.LV1Clicker(st, 0,
                   click_layer=lambda k, m, **kw: (clics.append(("couche", k, m)), (True, None))[1],
                   click_strip=lambda i, m, rgb=None, **kw: (clics.append(("tranche", i, m)), (True, None))[1],
                   click_mode=lambda name, n, m: (clics.append(("mode", name, m)), (True, None))[1],
                   click_all=lambda m: (clics.append(("onglet", None, m)), (True, None))[1],
                   jog=lambda n: (clics.append(("jog", n, st.view + 1)), (True, None))[1])
clk.WAIT_LAYER = 0.01

# demandes sur Mixer 1, puis passage sur Mixer 2 AVANT qu'elles ne partent (fil pas encore lancé)
clk.layer(2)
clk.mode("input")
clk.select(TRACK)
clk.all_tab()
clk.jog(3)
st.view = 1
# demandes sur Mixer 2
clk.layer(1)
clk.select(TRACK)
clk.start()
time.sleep(0.5)
print("clics :", clics)
annules = [m for m in MARKS if "annulé : Mixer changé" in m]
print("journal :", annules)
check("rien de Mixer 1 n'est cliqué", all(c[2] == 2 for c in clics))
check("5 demandes de Mixer 1 abandonnées", len(annules) == 5)
check("demandes de Mixer 2 cliquées", ("couche", 1, 2) in clics and ("tranche", 3, 2) in clics)

# deux sélections de Mixers différents, l'une derrière l'autre : pas fusionnées
del clics[:], MARKS[:]
st.view = 0
clk2 = D.LV1Clicker(st, 0, click_layer=lambda *a, **k: (True, None),
                    click_strip=lambda i, m, rgb=None, **kw: (clics.append(("tranche", i, m)), (True, None))[1],
                    click_mode=lambda *a: (True, None), click_all=lambda m: (True, None), jog=lambda n: (True, None))
clk2.select((0, 5))
st.view = 1
clk2.select((0, 7))
clk2.start()
time.sleep(0.3)
check("sélection Mixer 1 abandonnée, sélection Mixer 2 cliquée", clics == [("tranche", 7, 2)]
      and len([m for m in MARKS if "annulé" in m]) == 1)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
