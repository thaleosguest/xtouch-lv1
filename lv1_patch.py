#!/usr/bin/env python3
"""Patch B de la LV1 en diagonale, par clics dans la page Patch (demande de Joseph du 15-16/10/2026).

Diagonale : la n-ième ligne (voie) de la grille Input B -> canal n du pilote SoundGrid de Reaper. Elle casse quand un
canal passe de mono à stéréo (les lignes se décalent) : cet outil la refait. La LV1 n'a aucune commande réseau de
patch : on lit la grille À L'ÉCRAN et on clique les cases (PostMessage, souris immobile, comme lv1_clic).

Avant : LV1 sur la page Patch > Input > Input B, vignette du pilote sélectionnée (contour bleu), grille en haut
(pas défilée). PowerShell ADMINISTRATEUR (la LV1 l'est).

    py lv1_patch.py lire              # lit la grille, compare à la diagonale (aucun clic)
    py lv1_patch.py case 52 100       # ESSAI : clique UNE case (ligne 52, colonne 100) et dit ce qui a changé
    py lv1_patch.py diagonale         # affiche les clics nécessaires (aucun clic)
    py lv1_patch.py diagonale --go    # les fait, puis relit la grille

Géométrie relevée le 15/10 (1920x1080, vue réduite) : lignes de grille (120,120,120), pas 13 px, 1re colonne à
x 461, 1re ligne à y 356 ; case patchée (56,201,255), vide (17,17,17). Mesurée à chaque fois à l'écran (zoom libre).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lv1_clic as LC

GRID_LINE = (120, 120, 120)
CELL_ON = (56, 201, 255)
INPUT_B_BTN, INPUT_A_BTN = (100, 385), (100, 315)       # fonds des boutons Input B / Input A (allumé = bleu)
TILE_X0, TILE_PITCH, TILE_Y = 575, 106, 160             # vignettes d'appareils : contour gauche, pas, hauteur lue
GRID_X0, GRID_X1, GRID_Y0, GRID_Y1 = 455, 1880, 340, 1045
PROBE_Y, PROBE_X = 700, 1500                            # rangée / colonne où l'on cherche les lignes de la grille


class Screen:
    """Copie de l'écran (une seule capture GDI, puis lecture des pixels en mémoire)."""

    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        vp = ctypes.c_void_p
        u.GetDC.restype = g.CreateCompatibleDC.restype = g.CreateCompatibleBitmap.restype = vp
        u.GetDC.argtypes = [vp]
        g.CreateCompatibleDC.argtypes = [vp]
        g.CreateCompatibleBitmap.argtypes = [vp, ctypes.c_int, ctypes.c_int]
        g.SelectObject.argtypes = [vp, vp]
        g.BitBlt.argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, vp, ctypes.c_int,
                             ctypes.c_int, wt.DWORD]
        g.GetDIBits.argtypes = [vp, vp, wt.UINT, wt.UINT, vp, vp, wt.UINT]
        u.ReleaseDC.argtypes = [vp, vp]
        g.DeleteObject.argtypes = g.DeleteDC.argtypes = [vp]
        self.w, self.h = 1920, 1080
        sdc = u.GetDC(None)
        mdc = g.CreateCompatibleDC(sdc)
        bmp = g.CreateCompatibleBitmap(sdc, self.w, self.h)
        g.SelectObject(mdc, bmp)
        g.BitBlt(mdc, 0, 0, self.w, self.h, sdc, 0, 0, 0x00CC0020)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        bih = BIH(ctypes.sizeof(BIH), self.w, -self.h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.buf = ctypes.create_string_buffer(self.w * self.h * 4)
        g.GetDIBits(mdc, bmp, 0, self.h, self.buf, ctypes.byref(bih), 0)
        self.buf = self.buf.raw                       # bytes : un index donne un entier
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(None, sdc)

    def px(self, x, y):
        i = (y * self.w + x) * 4
        b, g, r = self.buf[i], self.buf[i + 1], self.buf[i + 2]
        return r, g, b


def close(a, b, tol=12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def read_grid(sc=None):
    """Lit la page Patch / Input B. Rend (grille, raison) : grille = {"cols": [x centres], "rows": [y centres],
    "on": {ligne: [colonnes patchées]}, "tile": n° de vignette sélectionnée (1-based)} ; raison si illisible."""
    t = LC.Target(1)
    if not t.hwnd:
        return None, "fenêtre LV1 introuvable"
    if t.rect != (0, 0, 1920, 1080):
        return None, "LV1 pas en plein écran 1920x1080 (%s)" % (t.rect,)
    if t.active_tab() != "Patch":
        return None, "la LV1 n'est pas sur la page Patch"
    sc = sc or Screen()
    if not close(sc.px(*INPUT_B_BTN), CELL_ON) or close(sc.px(*INPUT_A_BTN), CELL_ON):
        return None, "Input B n'est pas sélectionné (page Patch > Input > Input B)"
    tiles = [k + 1 for k in range(12) if TILE_X0 + TILE_PITCH * k < GRID_X1
             and close(sc.px(TILE_X0 + TILE_PITCH * k, TILE_Y), CELL_ON)]      # contour bleu = sélectionnée
    vx = [x for x in range(GRID_X0, GRID_X1) if sc.px(x, PROBE_Y) == GRID_LINE]
    hy = [y for y in range(GRID_Y0, GRID_Y1) if sc.px(PROBE_X, y) == GRID_LINE]
    if len(vx) < 10 or len(hy) < 10:
        return None, "grille introuvable"
    px_ = (vx[-1] - vx[0]) / (len(vx) - 1)
    py_ = (hy[-1] - hy[0]) / (len(hy) - 1)
    # la 1re colonne / ligne est à gauche / au-dessus de la 1re ligne de grille trouvée
    cols = [vx[0] - px_ / 2] + [vx[i] + px_ / 2 for i in range(len(vx) - 1)]
    rows = [hy[0] - py_ / 2] + [hy[i] + py_ / 2 for i in range(len(hy) - 1)]
    on = {}
    for r, y in enumerate(rows):
        hit = [c for c, x in enumerate(cols) if close(sc.px(int(round(x)), int(round(y))), CELL_ON, 20)]
        if hit:
            on[r] = hit
    return {"cols": cols, "rows": rows, "on": on, "tile": tiles[0] if tiles else None,
            "pitch": (round(px_, 2), round(py_, 2))}, None


def plan(grid, n=None):
    """Clics pour la diagonale ligne r -> colonne r (r < n, n = nb de colonnes visibles par défaut)."""
    n = min(n or len(grid["cols"]), len(grid["rows"]), len(grid["cols"]))
    add, remove = [], []
    for r in range(len(grid["rows"])):
        cur = grid["on"].get(r, [])
        want = [r] if r < n else []
        remove += [(r, c) for c in cur if c not in want]
        add += [(r, c) for c in want if c not in cur]
    return add, remove


def click_cell(grid, r, c):
    t = LC.Target(1)
    why = t.check()
    if why:
        return False, why
    return t.click(grid["cols"][c], grid["rows"][r]), None


def show(grid):
    print("grille : %d colonnes x %d lignes visibles, pas %s, vignette sélectionnée : %s"
          % (len(grid["cols"]), len(grid["rows"]), grid["pitch"], grid["tile"]))
    bad = [(r, cs) for r, cs in sorted(grid["on"].items()) if cs != [r]]
    print("cases patchées : %d lignes ; hors diagonale : %s" % (len(grid["on"]),
          ", ".join("ligne %d -> %s" % (r + 1, [c + 1 for c in cs]) for r, cs in bad) or "aucune"))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lire"
    grid, why = read_grid()
    if why:
        print("Impossible :", why)
        return 1
    show(grid)
    if cmd == "case":
        r, c = int(sys.argv[2]) - 1, int(sys.argv[3]) - 1
        before = grid["on"].get(r, [])
        ok, why = click_cell(grid, r, c)
        if not ok:
            print("clic refusé :", why)
            return 1
        time.sleep(0.6)
        after, _ = read_grid()
        print("ligne %d : avant %s -> après %s" % (r + 1, [x + 1 for x in before],
                                                    [x + 1 for x in (after or {"on": {}})["on"].get(r, [])]))
        return 0
    if cmd == "diagonale":
        n = None
        if "--n" in sys.argv:
            n = int(sys.argv[sys.argv.index("--n") + 1])
        add, remove = plan(grid, n)
        print("à retirer : %s" % ([(r + 1, c + 1) for r, c in remove] or "rien"))
        print("à ajouter : %s" % ([(r + 1, c + 1) for r, c in add] or "rien"))
        if "--go" not in sys.argv:
            print("(rien n'est cliqué : ajoute --go pour le faire)")
            return 0
        for r, c in remove + add:
            ok, why = click_cell(grid, r, c)
            if not ok:
                print("clic refusé :", why)
                return 1
            time.sleep(0.15)
        time.sleep(0.6)
        grid2, why = read_grid()
        if why:
            print("relecture impossible :", why)
            return 1
        add2, remove2 = plan(grid2, n)
        print("après : %s" % ("diagonale OK" if not add2 and not remove2 else "reste %s" % (add2 + remove2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
