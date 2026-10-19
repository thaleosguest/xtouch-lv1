#!/usr/bin/env python3
"""Patch B de la LV1 en diagonale, par clics dans la page Patch (demande de Joseph du 15-16/10/2026).

Diagonale : la n-ième ligne (voie) de la grille Input B -> canal n du pilote SoundGrid de Reaper. Elle casse quand un
canal passe de mono à stéréo (les lignes se décalent) : cet outil la refait. La LV1 n'a aucune commande réseau de
patch : on lit la grille À L'ÉCRAN et on clique les cases (PostMessage, souris immobile, comme lv1_clic).

Avant : LV1 sur la page Patch > Input > Input B, vignette du pilote sélectionnée (contour bleu), grille en haut
(pas défilée). PowerShell ADMINISTRATEUR (la LV1 l'est).

    py lv1_patch.py lire              # lit la grille, compare à la diagonale (aucun clic)
    py lv1_patch.py case 52 100       # ESSAI : clique UNE case (ligne 52, colonne 100) et dit ce qui a changé
    py lv1_patch.py diagonale [--n 48]   # affiche les clics nécessaires (aucun clic) ; --n : nb de lignes à patcher
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
PROBE_YS, PROBE_XS = (700, 806, 910), (1500, 1300)      # rangées / colonnes où l'on cherche les lignes de la grille
# Grille en haut à gauche (pas défilée) : le curseur des ascenseurs touche le début de leur rail (relevé le 16/10).
# Défilée, la 1re ligne visible n'est plus la ligne 1 : on refuse (essais de Joseph : « ligne 1 -> [42] »).
SCROLL_THUMB = (231, 231, 231)
ZOOM_OUT_BTN = (148, 244)          # loupe « − » au-dessus de la liste des canaux (relevé le 16/10)
VSCROLL_TOP, HSCROLL_LEFT = (1891, 230), (131, 1055)
TILE_LAST_X = 1700                 # au-delà : vignette ROUTING / flèche (vignettes défilées : refus)
TILE_CLICK_DX, TILE_CLICK_Y = 45, 175   # clic dans une vignette : à droite de son contour, sous son bandeau
FAST_GAP = 0.02                    # s entre deux clics de case (19/10 : 0,25 s par case avant, capture comprise)
CHECK_EVERY = 16                   # clics entre deux contrôles légers de l'onglet


class Screen:
    """Image de la fenêtre LV1 (une seule capture GDI, puis lecture des pixels en mémoire). hwnd donné : PrintWindow
    de la fenêtre elle-même, même cachée par d'autres fenêtres (16/10 : PowerShell et Claude couvraient la grille ->
    ascenseurs mal lus) ; refusé hors administrateur -> copie de l'écran (la LV1 doit alors être visible)."""

    def __init__(self, hwnd=None):
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
        u.PrintWindow.argtypes = [vp, vp, wt.UINT]
        self.source = "écran"
        if hwnd and u.PrintWindow(hwnd, mdc, 3):          # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            self.source = "fenêtre LV1"
        else:
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
    sc = sc or Screen(t.hwnd)
    tab = [n for n, x in LC.TABS.items() if close(sc.px(x, LC.TAB_READ_Y), LC.TAB_ACTIVE)]
    if tab != ["Patch"]:
        return None, "la LV1 n'est pas sur la page Patch (lu : %s, image : %s)" % (tab or "?", sc.source)
    if not close(sc.px(*INPUT_B_BTN), CELL_ON) or close(sc.px(*INPUT_A_BTN), CELL_ON):
        return None, "Input B n'est pas sélectionné (page Patch > Input > Input B)"
    tiles = [k + 1 for k in range(12) if TILE_X0 + TILE_PITCH * k < GRID_X1
             and close(sc.px(TILE_X0 + TILE_PITCH * k, TILE_Y), CELL_ON)]      # contour bleu = sélectionnée
    if not close(sc.px(*VSCROLL_TOP), SCROLL_THUMB) or not close(sc.px(*HSCROLL_LEFT), SCROLL_THUMB):
        return None, "grille défilée : remonte-la tout en haut et tout à gauche (ascenseurs au début)"
    # plusieurs rangées / colonnes d'essai : celle du canal sélectionné est surlignée (lignes d'une autre couleur)
    vx = max(([x for x in range(GRID_X0, GRID_X1) if sc.px(x, y) == GRID_LINE] for y in PROBE_YS), key=len)
    hy = max(([y for y in range(GRID_Y0, GRID_Y1) if sc.px(x, y) == GRID_LINE] for x in PROBE_XS), key=len)
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
    return {"cols": cols, "rows": rows, "on": on, "tile": tiles[0] if tiles else None, "source": sc.source,
            "pitch": (round(px_, 2), round(py_, 2))}, None


def plan(grid, n=None):
    """Clics pour la diagonale ligne r -> colonne r (r < n, n = nb de colonnes visibles par défaut)."""
    n = min(n or len(grid["cols"]), len(grid["rows"]), len(grid["cols"]))
    add, extra = [], []
    for r in range(len(grid["rows"])):
        cur = grid["on"].get(r, [])
        if r < n:
            if cur != [r]:
                add.append((r, r))          # le clic remplace la source de la ligne
        elif cur:
            extra.append((r, cur[0]))       # ligne au-delà de la diagonale encore patchée : signalée, pas touchée
    return add, extra


def click_cell(grid, r, c):
    """Un clic sur une case REMPLACE la source de la ligne (essai de Joseph du 16/10 : ligne 4, clic colonne 18 ->
    [18], la 4 a disparu) : pas besoin de retirer l'ancienne avant."""
    t = LC.Target(1)
    if not LC.is_admin():
        return False, "pas administrateur (la LV1 l'est : Windows bloquerait le clic)"
    if not t.hwnd or LC.u32().IsIconic(t.hwnd):
        return False, "fenêtre LV1 introuvable ou réduite"
    sc = Screen(t.hwnd)
    if not close(sc.px(LC.TABS["Patch"], LC.TAB_READ_Y), LC.TAB_ACTIVE):
        return False, "la LV1 n'est plus sur la page Patch"
    return t.click(grid["cols"][c], grid["rows"][r]), None


def zoom_out(grid, max_clicks=8):
    """Dézoome la grille au maximum (loupe « − ») pour voir toutes les lignes (Joseph, 16/10 : zoomée, seule la partie
    visible de la diagonale était refaite). S'arrête quand les cases ne rapetissent plus. Rend la grille relue."""
    t = LC.Target(1)
    for _ in range(max_clicks):
        if not LC.is_admin():
            return grid, "pas administrateur"
        t.click(*ZOOM_OUT_BTN)
        time.sleep(0.25)
        g2, why = read_grid()
        if why:
            return grid, why
        if g2["pitch"] >= grid["pitch"]:              # plus petit possible atteint
            return g2, None
        grid = g2
    return grid, None


def select_tile(grid, tile, name=None):
    """Vignette `tile` (1-based) sélectionnée, sinon on clique dessus (19/10, demande de Joseph : ENTER ne doit
    jamais patcher un autre appareil). Rend (grille relue, raison si impossible)."""
    if grid["tile"] == tile:
        return grid, None
    x = TILE_X0 + TILE_PITCH * (tile - 1)
    if x + TILE_CLICK_DX > TILE_LAST_X:
        return grid, "vignette %d (%s) hors de vue : la sélectionner à la main" % (tile, name or "pilote")
    if not LC.is_admin():
        return grid, "pas administrateur"
    LC.Target(1).click(x + TILE_CLICK_DX, TILE_CLICK_Y)
    time.sleep(0.5)
    g2, why = read_grid()
    if why:
        return grid, why
    if g2["tile"] != tile:
        return g2, "vignette %d (%s) pas sélectionnée (lu : %s)" % (tile, name or "pilote", g2["tile"])
    return g2, None


def matches_db(grid, expect):
    """Les cases patchées à l'écran sont-elles celles que la base donne pour le pilote ? expect = {ligne: colonne}
    (lignes de l'entrée B branchées sur le pilote). Seules les lignes VISIBLES comptent ; aucune : True. Garde-fou contre
    une vignette défilée ou mal numérotée : au moins la moitié des lignes visibles attendues doivent correspondre."""
    seen = {r: c for r, c in expect.items() if r < len(grid["rows"]) and c < len(grid["cols"])}
    if not seen:                       # 19/10 : comparer des lignes hors de l'écran les comptait fausses -> refus en série
        return True
    same = sum(1 for r, c in seen.items() if grid["on"].get(r) == [c])
    return same * 2 >= len(seen)


def click_fast(grid, cells):
    """Clique les cases à la suite (FAST_GAP), contrôle léger de l'onglet toutes les CHECK_EVERY cases. Rend raison
    ou None."""
    t = LC.Target(1)
    if not LC.is_admin():
        return "pas administrateur (la LV1 l'est : Windows bloquerait le clic)"
    if not t.hwnd or LC.u32().IsIconic(t.hwnd):
        return "fenêtre LV1 introuvable ou réduite"
    t.traverse = True
    for i, (r, c) in enumerate(cells):
        if i % CHECK_EVERY == 0 and i and t.active_tab() != "Patch":
            return "la LV1 n'est plus sur la page Patch"
        t.click(grid["cols"][c], grid["rows"][r])
        time.sleep(FAST_GAP)
    return None


def fix_diagonal(n=None, log=lambda m: None, tile=None, expect=None, name=None, passes=3):
    """Refait la diagonale (Patch > Input B ouvert) : vignette du pilote, dézoom si besoin, clics rapides, relecture,
    nouvelle passe pour les ratés. Rend (réussi, message). Utilisé par `diagonale --go`, ENTER de la X-Touch et le
    bouton REALIGN de l'écran (pont). tile : vignette du pilote (rang dans la rangée, lv1_db.driver_info) ; expect : {ligne: colonne} de la base
    pour ce pilote ; n : nombre de lignes à patcher (voies des entrées, au plus la taille du pilote)."""
    grid, why = read_grid()
    if why:
        return False, "impossible : " + why
    if tile:
        grid, why = select_tile(grid, tile, name)
        if why:
            return False, "impossible : " + why
    if not matches_db(grid, expect):
        return False, ("impossible : la grille affichée ne correspond pas à %s dans la base (vignette défilée ?)"
                       % (name or "au pilote"))
    if not n or len(grid["rows"]) < n:
        grid, why = zoom_out(grid)
        if why:
            return False, "dézoom impossible : " + why
        log("après dézoom : %d colonnes x %d lignes visibles" % (len(grid["cols"]), len(grid["rows"])))
    add, _ = plan(grid, n)
    total, add2, grid2 = 0, add, grid
    for _p in range(passes):
        if not add2:
            break
        why = click_fast(grid2, add2)
        if why:
            return False, "clic refusé : " + why
        total += len(add2)
        time.sleep(0.4)
        grid2, why = read_grid()
        if why:
            return False, "relecture impossible : " + why
        add2, _ = plan(grid2, n)
    msg = "%d case(s) corrigée(s) ; " % total + ("diagonale OK" if not add2 else
                                                     "reste %s" % [(r + 1, c + 1) for r, c in add2])
    if n and n > len(grid2["rows"]):
        msg += " ; ATTENTION : %d lignes demandées, %d seulement visibles même dézoomé" % (n, len(grid2["rows"]))
    return not add2, msg


def show(grid):
    print("grille : %d colonnes x %d lignes visibles, pas %s, vignette sélectionnée : %s (image : %s)"
          % (len(grid["cols"]), len(grid["rows"]), grid["pitch"], grid["tile"], grid["source"]))
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
        add, extra = plan(grid, n)
        print("à cliquer (ligne, colonne) : %s" % ([(r + 1, c + 1) for r, c in add] or "rien"))
        if extra:
            print("lignes après la diagonale encore patchées (non touchées) : %s" % [(r + 1, c + 1) for r, c in extra])
        if "--go" not in sys.argv:
            print("(rien n'est cliqué : ajoute --go pour le faire ; la grille sera d'abord dézoomée au maximum)")
            return 0
        ok, msg = fix_diagonal(n)
        print(msg)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
