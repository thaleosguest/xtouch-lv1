"""Test : depuis l'onglet Channel, la LV1 allume l'onglet Mixer AVANT d'avoir redessiné les tranches (essai du 19/10,
journal 135225 : 1 sélection sur ~20 passait, « bande du nom introuvable »). Le pont doit relire la page un moment
(REDRAW_WAIT) au lieu d'abandonner à la 1re lecture.
- garde-fou (couches, modes) : faux les 3 premières lectures, puis vrai -> l'action part, une seule fois ;
- action réessayable (bande du nom : rien cliqué tant qu'elle n'est pas trouvée) -> réessayée jusqu'au succès ;
- jamais dessiné -> refus après REDRAW_WAIT, retour sur Channel ; déjà sur Mixer -> une seule lecture (comme avant).

    py tests/test_aller_retour_onglet.py .
"""
import sys, time
sys.path.insert(0, sys.argv[1])
import lv1_clic as C

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


def fausse_lv1(onglet_depart="Channel"):
    """Target sans vraie fenêtre : l'onglet change au clic d'onglet, les clics sont notés."""
    t = C.Target.__new__(C.Target)
    t.mixer, t.detached, t.hwnd, t.rect = 1, False, 1, (0, 0, 1920, 1080)
    t.onglet, t.clics = onglet_depart, []

    def click(rx, ry, method="message"):
        t.clics.append((rx, ry))
        for nom, x in C.TABS.items():
            if rx == x and ry == C.TAB_Y:
                t.onglet = nom
        return True
    t.click = click
    t.active_tab = lambda: t.onglet
    return t


def dessine_apres(n):
    """Garde-fou : « pas dessiné » pour les n premières lectures, puis bon."""
    lectures = [0]
    def frame(_t):
        lectures[0] += 1
        return "case pas encore dessinée" if lectures[0] <= n else None
    frame.lectures = lectures
    return frame


# 1) garde-fou faux 3 fois puis vrai : l'action part une fois, retour sur Channel
t = fausse_lv1()
f = dessine_apres(3)
actions = []
res = t.on_mixer(f, lambda: (actions.append(1), True)[1])
check("garde-fou : relu jusqu'au dessin", res == (True, None) and f.lectures[0] == 4 and actions == [1])
check("retour sur Channel", t.onglet == "Channel" and t.clics[0] == (C.TABS["Mixer 1"], C.TAB_Y)
      and t.clics[-1] == (C.TABS["Channel"], C.TAB_Y))

# 2) action réessayable (bande du nom) : trouvée à la 3e lecture -> succès, un seul clic de tranche
t = fausse_lv1()
essais = [0]
def act():
    essais[0] += 1
    if essais[0] < 3:
        return False                                 # bande introuvable : rien cliqué
    t.click(500, 433)
    return True
act.retry = True
res = t.on_mixer(None, act)
tranche = [c for c in t.clics if c == (500, 433)]
check("action réessayée jusqu'au succès", res[0] is True and essais[0] == 3 and len(tranche) == 1)

# 3) jamais dessiné : refus après REDRAW_WAIT, retour sur Channel
t = fausse_lv1()
t0 = time.time()
res = t.on_mixer(dessine_apres(10 ** 6), lambda: True)
dt = time.time() - t0
check("jamais dessiné : refus", res[0] is False and "page Mixer" in res[1] and t.onglet == "Channel")
check("attente bornée", C.REDRAW_WAIT - 0.05 <= dt <= C.REDRAW_WAIT + 0.4)

# 4) déjà sur Mixer : pas d'aller-retour, action non réessayée (comportement d'avant)
t = fausse_lv1("Mixer 1")
essais = [0]
def act2():
    essais[0] += 1
    return False
act2.retry = True
res = t.on_mixer(None, act2)
check("sur Mixer : une seule lecture", res[0] is False and essais[0] == 1 and t.clics == [])

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
