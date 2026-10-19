"""Test : patch Input B sécurisé et plus rapide, alerte de la page Patch (demande de Joseph, 19/10/2026).
- fix_diagonal sélectionne la vignette du pilote (assign + 1) si une autre l'est ; refuse si elle est hors de vue ;
- refus SANS clic si la grille affichée ne correspond pas à la base pour ce pilote (vignette défilée…) ;
- clics à la suite, puis relecture et 2e passe pour les cases ratées ; pas de dézoom si toutes les lignes sont visibles ;
- patch_alert : rien hors page Patch, « idle » / « busy » / « failed » + consigne anglaise / « done » ;
- canal retour UDP : send_action de l'overlay -> on_action (« fix_patch ») / on_log (traces) du pont.

    py tests/test_patch_b.py .
"""
import io, sys
sys.path.insert(0, sys.argv[1])
import lv1_patch as P
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


# ── fausse page Patch : grille 6x6, vignette sélectionnée, clics enregistrés (une case ratée au 1er passage)
class FauxLV1:
    def __init__(self, tile=1, on=None, rows=6):
        self.tile, self.on, self.rows = tile, dict(on or {}), rows
        self.clicks, self.tile_clicks, self.zooms, self.rate = [], [], 0, {(3, 3)}

    def grid(self):
        return {"cols": [10.0 * c for c in range(6)], "rows": [10.0 * r for r in range(self.rows)],
                "on": {r: list(v) for r, v in self.on.items()}, "tile": self.tile, "pitch": (13, 13), "source": "test"}

    def click(self, x, y):
        if y == P.TILE_CLICK_Y:
            self.tile = int(round((x - P.TILE_CLICK_DX - P.TILE_X0) / P.TILE_PITCH)) + 1
            self.tile_clicks.append(self.tile)
            return True
        if (x, y) == tuple(P.ZOOM_OUT_BTN):
            self.zooms += 1
            return True
        r, c = int(round(y / 10)), int(round(x / 10))
        self.clicks.append((r, c))
        if (r, c) in self.rate:
            self.rate.discard((r, c))              # ratée une fois : la 2e passe doit la refaire
        else:
            self.on[r] = [c]
        return True


lv1 = None


class FauxTarget:
    hwnd, traverse = 1, False
    def __init__(self, mixer=1): pass
    def click(self, x, y, method="message"): return lv1.click(x, y)
    def active_tab(self): return "Patch"


P.read_grid = lambda sc=None: (lv1.grid(), None)
P.LC.Target = FauxTarget
P.LC.is_admin = lambda: True
P.LC.u32 = lambda: type("U", (), {"IsIconic": staticmethod(lambda h: False)})()
P.time = type("T", (), {"sleep": staticmethod(lambda s: None)})()   # lv1_patch seulement

# 1) mauvaise vignette (X32 = 1) : le pilote (vignette 2) est sélectionné, puis la diagonale est refaite en 2 passes
lv1 = FauxLV1(tile=1, on={0: [0], 1: [1], 2: [5], 4: [4]})
res = P.fix_diagonal(n=6, tile=2, expect={0: 0, 1: 1}, name="LV1-PORT")
print("1)", res, "clics :", lv1.clicks)
check("vignette du pilote sélectionnée", lv1.tile_clicks == [2])
check("diagonale refaite, case ratée reprise", res[0] and all(lv1.on.get(r) == [r] for r in range(6))
      and lv1.clicks.count((3, 3)) == 2)
check("pas de dézoom (6 lignes visibles)", lv1.zooms == 0)

# 2) grille qui ne correspond pas à la base : refus, aucun clic
lv1 = FauxLV1(tile=2, on={0: [3], 1: [4]})
res = P.fix_diagonal(n=6, tile=2, expect={0: 0, 1: 1}, name="LV1-PORT")
print("2)", res)
check("grille ≠ base : refus sans clic", not res[0] and lv1.clicks == [] and "ne correspond pas" in res[1])

# 3) vignette hors de vue : refus
lv1 = FauxLV1(tile=1)
res = P.fix_diagonal(n=6, tile=12, expect={}, name="LV1-PORT")
check("vignette hors de vue : refus", not res[0] and "hors de vue" in res[1] and lv1.tile_clicks == [])


# ── alerte de la page Patch
class Apps:
    fixing, fix_result = False, None

a = Apps()
check("hors page Patch : rien", D.patch_alert("Mixer 1", ["In 3"], a, "LV1-PORT", 100.0) is None)
check("page Patch, rien de cassé : rien", D.patch_alert("Patch", [], a, "LV1-PORT", 100.0) is None)
check("idle", D.patch_alert("Patch", ["In 3", "In 4"], a, "LV1-PORT", 100.0)
      == {"bad": 2, "device": "LV1-PORT", "state": "idle"})
a.fixing = True
check("busy", D.patch_alert("Patch", ["In 3"], a, "LV1-PORT", 100.0)["state"] == "busy")
a.fixing, a.fix_result = False, (False, "impossible : Input B n'est pas sélectionné (page Patch > Input > Input B)", 99.0)
al = D.patch_alert("Patch", ["In 3"], a, "LV1-PORT", 100.0)
check("failed + consigne anglaise", al["state"] == "failed" and al["hint"].startswith("Open Patch"))
a.fix_result = (True, "2 case(s) corrigée(s)", 99.0)
check("done tant que la base n'est pas relue", D.patch_alert("Patch", ["In 3"], a, "LV1-PORT", 100.0)["state"] == "done")
check("done puis disparaît", D.patch_alert("Patch", [], a, "LV1-PORT", 99.0 + D.PATCH_DONE_S + 0.5) is None)

# ── clic REALIGN : message UDP de l'overlay (send_action) -> on_action / on_log, de bout en bout
import socket, threading, time
import xtouch_overlay as O
qo = O.QtOverlay.__new__(O.QtOverlay)
qo.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
qo.rx.bind(("127.0.0.1", 0))
got, logs = [], []
qo.on_action, qo.on_log = got.append, logs.append
threading.Thread(target=qo._read_actions, daemon=True).start()
from PySide6.QtWidgets import QApplication
import xtouch_overlay_qt as Q
Q.RETOUR = qo.rx.getsockname()[1]
Q.send_action("overlay démarré, canal retour OK", "log")
Q.send_action("fix_patch")
t_end = time.time() + 3
while time.time() < t_end and not (got and logs):
    time.sleep(0.02)
check("clic REALIGN transmis au pont", got == ["fix_patch"])
check("trace de l'overlay transmise", logs == ["overlay démarré, canal retour OK"])
qo.handle_back(b'bruit')
check("message illisible ignoré", got == ["fix_patch"])

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
