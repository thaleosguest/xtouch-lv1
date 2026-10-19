"""Test : pas de changement de Mixer pendant qu'un fader est touché (étape 10, correctif 1, 19/10/2026).
Sinon le fader tenu écrivait sur la tranche du même numéro dans l'autre Mixer.
- onglet Mixer 2 affiché, fader tenu : la vue reste Mixer 1, noté UNE fois au journal ; voyant GLOBAL VIEW (lv1_tab) suivi ;
- lâché : bascule sur Mixer 2 à la lecture suivante ;
- tenu, retour sur Mixer 1 avant le lâcher : rien ne change ;
- --mixer imposé : inchangé (jamais de bascule).

    py tests/test_mixer_toucher.py .
"""
import sys
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

hint, tenu = [("Mixer 1", None)], [False]
st = D.LV1State()
f = D.ViewFollower(st, None, read=lambda: hint[0], busy=lambda: tenu[0])

f.step()
check("départ Mixer 1", st.view == 0)
tenu[0] = True
hint[0] = ("Mixer 2", None)
for _ in range(3):
    f.step()
check("tenu : reste sur Mixer 1", st.view == 0)
check("onglet suivi quand même (GLOBAL VIEW)", st.lv1_tab == "Mixer 2")
diff = [m for m in MARKS if "différé" in m]
check("noté une seule fois", len(diff) == 1)
tenu[0] = False
f.step()
check("lâché : bascule sur Mixer 2", st.view == 1)

# tenu, puis retour sur Mixer 1 avant le lâcher : rien ne change
tenu[0] = True
hint[0] = ("Mixer 1", None)
f.step()
hint[0] = ("Mixer 2", None)
f.step()
check("tenu sur Mixer 2 -> Mixer 1 différé", st.view == 1)
hint[0] = ("Mixer 2", None)
tenu[0] = False
f.step()
check("revenu avant le lâcher : reste Mixer 2", st.view == 1)

# fenêtre Mixer détachée au premier plan : même règle
tenu[0] = True
hint[0] = ("All", 1)
f.step()
check("fenêtre MIXER1 devant, tenu : différé", st.view == 1)
tenu[0] = False
f.step()
check("lâché : Mixer 1", st.view == 0)

# vue imposée (--mixer 2) : jamais de bascule, tenu ou pas
st2 = D.LV1State()
st2.view = 1
g = D.ViewFollower(st2, 1, read=lambda: ("Mixer 1", None), busy=lambda: True)
g.step()
check("--mixer imposé : inchangé", st2.view == 1)

print("journal :", MARKS)
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
