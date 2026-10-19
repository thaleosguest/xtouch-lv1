"""Test : une fenêtre couvre la LV1 (essai du 19/10, journal 135225 : tranches 6-10 refusées, « bande du nom
introuvable », les 11-14 visibles passaient). Pour un clic VOULU, le pont relit dans l'image de la fenêtre LV1
(PrintWindow) quand l'écran ne montre pas la LV1 ; pour les lectures périodiques, jamais.
- garde-fou : écran faux, fenêtre bonne -> accepté et noté (used_window) ; sans `traverse` -> refusé, fenêtre pas lue ;
- onglet : illisible à l'écran, lu dans la fenêtre seulement pour un clic voulu ;
- sélection de bout en bout (click_strip) : écran couvert -> bande trouvée dans la fenêtre, clic au bon endroit,
  journal « vu à travers la fenêtre… » ; PrintWindow refusé (pas administrateur) -> refus comme avant.

    py tests/test_fenetre_devant.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import lv1_clic as C

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

GRIS = (40, 40, 40)                                   # la fenêtre posée sur la LV1
CANAL = (200, 50, 50)                                 # couleur du canal de la tranche cliquée


def cible():
    t = C.Target.__new__(C.Target)
    t.mixer, t.detached, t.hwnd, t.rect = 1, False, 1, (0, 0, 1920, 1080)
    t.traverse, t.used_window = False, False
    return t


# 1) garde-fou
lus = []
t = cible()
t.reader = lambda box: (lambda x, y: GRIS)
t.window_reader = lambda box: (lus.append(box), lambda x, y: (160, 160, 160))[1]
fn = lambda r: None if r(0, 0) == (160, 160, 160) else "pas vu"
check("lecture périodique : refus, fenêtre pas lue", t.guard((0, 0, 1, 1), fn) == "pas vu" and lus == [])
t.traverse = True
check("clic voulu : accepté via la fenêtre", t.guard((0, 0, 1, 1), fn) is None and t.used_window and len(lus) == 1)
t2 = cible(); t2.traverse = True
t2.reader = lambda box: (lambda x, y: GRIS)
t2.window_reader = lambda box: None                   # PrintWindow refusé
check("PrintWindow refusé : refus comme avant", t2.guard((0, 0, 1, 1), fn) == "pas vu" and not t2.used_window)


# 2) de bout en bout : sélection d'une tranche couverte
def faux_ecran(x, ys, w):
    return [[GRIS] * w for _ in ys]


def fausse_fenetre(hwnd, cx, ys, w):
    if ys == [C.TAB_READ_Y]:                          # rangée des onglets : Mixer 1 actif
        return [[C.TAB_ACTIVE if abs((cx + i) - C.TABS["Mixer 1"]) <= 3 else (231, 231, 231) for i in range(w)]]
    # colonne d'une tranche : bande du nom (couleur du canal) en y 420..445, fond sombre ailleurs
    return [[CANAL if 420 <= yy <= 445 else (17, 17, 17)] * w for yy in ys]


clics = []
sauve = (C.screen_rows, C.window_rows, C.lv1_window, C.client_rect, C.is_admin, C.Target.click)
C.screen_rows, C.window_rows = faux_ecran, fausse_fenetre
C.lv1_window, C.client_rect, C.is_admin = (lambda m=1: (1, False)), (lambda h: (0, 0, 1920, 1080)), (lambda: True)
C.Target.click = lambda self, rx, ry, method="message": (clics.append((rx, round(ry))), True)[1]
C.u32 = lambda: type("U", (), {"IsIconic": staticmethod(lambda h: False)})()
res = C.click_strip(5, 1, rgb=CANAL)
print("sélection tranche 6, LV1 couverte :", res, clics)
check("tranche couverte : cliquée via la fenêtre", res[0] is True and "vu à travers" in (res[1] or "")
      and clics == [(C.strip_point(5)[0], round((420 + 445) / 2))])   # centre de la bande

clics.clear()
C.window_rows = lambda *a: None                       # pont pas administrateur : PrintWindow refusé
res = C.click_strip(5, 1, rgb=CANAL)
check("sans PrintWindow : refus comme avant", res[0] is False and clics == [])
C.screen_rows, C.window_rows, C.lv1_window, C.client_rect, C.is_admin, C.Target.click = sauve

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
