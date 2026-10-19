#!/usr/bin/env python3
"""Clics simulés dans la fenêtre de la LV1 (couches, sélection) — l'API réseau n'a pas ces commandes.

Essai (hors concert), dans un PowerShell lancé EN ADMINISTRATEUR (la LV1 l'est : Windows refuse sinon) :
    py lv1_clic.py verifier            # ne clique pas : dit ce qui serait fait et pourquoi
    py lv1_clic.py couche 2            # clique la 2e case de couche (Ch 17-32 en usine)
    py lv1_clic.py tranche 5           # clique le nom de la tranche 5 (sélection)
    py lv1_clic.py selection           # lit à l'écran la tranche sélectionnée (sans clic, sans admin)
    py lv1_clic.py molette 5           # page Channel : 5 crans de molette sur le fader de plugin du bas (-5 : baisse)
Options : --mixer 2, --methode souris (SendInput : bouge vraiment la souris, LV1 devant).

Géométrie relevée le 14/10/2026 sur la LV1 V17 de Joseph, page Mixer plein écran 1920x1080, en
fractions de la zone client (marche à d'autres tailles si la LV1 garde ses proportions) :
- cases de couche : colonne de droite, x 1847, y 537 + 72 x k (k = 0..7) ;
- nom des tranches : y 433, x 142 + 46 + 96 x i (i = 0..15) ;
- onglets : « Mixer 1 » centré x 651, « Mixer 2 » x 749, y 28 ; actif = bleu (56, 201, 255).
Garde-fous avant CHAQUE clic : administrateur, fenêtre LV1 trouvée et non réduite, onglet Mixer voulu
lu à l'écran (donc LV1 visible), cadre de la case de couche présent. Sinon : pas de clic.
"""
import argparse
import ctypes
import sys
import time
from ctypes import wintypes as wt

from lv1.layout import (REF_W, REF_H, TABS, TAB_READ_Y, TAB_Y, TAB_ACTIVE, TAB_X, LAYER_X, LAYER_Y0,
                        LAYER_PITCH, LAYER_EDGE, MODE_BUTTONS, MODE_ROW_Y, MODE_SPANS, MODES_80, MODES_64,
                        SPILL_ON, SPILL_PTS, STRIP_X0, STRIP_PITCH, STRIP_NAME_Y, NAME_SCAN, NAME_H, NAME_DX,
                        SEL_TOP_ROWS, SEL_YELLOW, SEL_X0, SEL_PITCH, BOTTOM_Y, BOTTOM_X, BOTTOM_GREY)

HOP_WAIT = 0.6        # s max pour que la LV1 affiche l'onglet cliqué
# Après le clic d'onglet, la LV1 allume l'ONGLET avant d'avoir redessiné les TRANCHES (essai du 19/10, journal 135225 :
# depuis Channel, 1 sélection sur ~20 passait, « bande du nom introuvable » ; empiré quand les lectures sont passées de
# 1-2 s à 30 ms en 0.2.1 : la lenteur laissait le temps au dessin). On relit donc la page pendant au plus REDRAW_WAIT s.
REDRAW_WAIT = 0.5

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0200, 0x0201, 0x0202, 0x0001

from lv1.screen import user32 as u32, lv1_window, client_rect, pixel, screen_rows, window_rows, close as _close


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


class Target:
    """Fenêtre LV1 + conversion des coordonnées de référence (1920x1080) en coordonnées client."""

    def __init__(self, mixer=1):
        self.mixer = mixer
        self.hwnd, self.detached = lv1_window(mixer)
        self.rect = client_rect(self.hwnd) if self.hwnd else None
        # Clic VOULU (Select, BANK, touches View) : si la lecture de l'écran échoue (fenêtre posée sur la LV1), on relit
        # dans l'image de la fenêtre LV1 (PrintWindow, 19/10). Faux pour les lectures périodiques : PrintWindow fait
        # redessiner la LV1, pas question de le faire 5 fois par seconde.
        self.traverse = False
        self.used_window = False      # la décision a été prise sur l'image de la fenêtre (noté dans le journal)

    def pt(self, rx, ry):
        x, y, w, h = self.rect
        return round(rx * w / REF_W), round(ry * h / REF_H)

    def screen(self, rx, ry):
        cx, cy = self.pt(rx, ry)
        return self.rect[0] + cx, self.rect[1] + cy

    def check(self, frame=None, tabs=True):
        """None si on peut cliquer, sinon la raison (texte). frame : point (x, y) d'un cadre clair attendu, ou
        fonction (target) -> raison ou None. tabs=False : n'importe quel onglet (bascule de l'onglet All)."""
        if not is_admin():
            return "pas administrateur (la LV1 l'est : Windows bloquerait le clic)"
        if not self.hwnd:
            return "fenêtre LV1 introuvable"
        if u32().IsIconic(self.hwnd):
            return "LV1 réduite"
        if not self.rect or self.rect[2] < 800:
            return "zone client LV1 illisible"
        if not tabs:
            return None
        if not self.detached:
            tab = self.active_tab()
            if tab not in ("Mixer %d" % self.mixer, "Channel"):
                return "onglet Mixer %d (ou Channel) pas affiché (lu : %s ; LV1 cachée ?)" % (self.mixer, tab)
            if tab == "Channel":
                return None            # aller-retour d'onglet : la case sera vérifiée sur la page Mixer
        return self.frame_why(frame)

    def frame_why(self, frame):
        if frame is None:
            return None
        if callable(frame):
            return frame(self)
        c = pixel(*self.screen(*frame))
        if c is None or sum(c) < 150:
            return "cadre de la case attendu en %s introuvable (couleur %s)" % (frame, c)
        return None

    def reader(self, box):
        """Une seule capture GDI de la zone box = (x0, y0, x1, y1) en pixels de référence 1920x1080 ; renvoie
        read(x, y) (référence) -> (r, g, b) ou None hors zone. GetPixel coûte 15-30 ms PAR point (journal du 16/10 :
        ~60 points lus un à un = 1 à 2 s avant chaque clic de mode)."""
        x0, y0 = self.screen(box[0], box[1])
        x1, y1 = self.screen(box[2], box[3])
        try:
            rows = screen_rows(x0, list(range(y0, y1 + 1)), x1 - x0 + 1)
        except Exception:
            return lambda x, y: None

        def read(x, y):
            sx, sy = self.screen(x, y)
            return rows[sy - y0][sx - x0] if (x0 <= sx <= x1 and y0 <= sy <= y1) else None
        return read

    def window_reader(self, box):
        """Comme reader, mais dans l'image de la fenêtre LV1 (PrintWindow) : voit à travers une fenêtre posée dessus.
        None si Windows refuse. Seulement en secours d'un clic voulu (self.traverse)."""
        x0, y0 = self.pt(box[0], box[1])
        x1, y1 = self.pt(box[2], box[3])
        try:
            rows = window_rows(self.hwnd, x0, list(range(y0, y1 + 1)), x1 - x0 + 1)
        except Exception:
            rows = None
        if rows is None:
            return None

        def read(x, y):
            cx, cy = self.pt(x, y)
            return rows[cy - y0][cx - x0] if (x0 <= cx <= x1 and y0 <= cy <= y1 and cx - x0 < len(rows[0])) else None
        return read

    def guard(self, box, fn):
        """Garde-fou fn(read) -> raison ou None, lu à l'écran ; en cas d'échec et de clic voulu, relu dans la fenêtre."""
        why = fn(self.reader(box))
        if why and self.traverse:
            r = self.window_reader(box)
            if r is not None and fn(r) is None:
                self.used_window = True
                return None
        return why

    def active_tab(self):
        """Onglet affiché (« Mixer 1 », « Channel »…) lu à l'écran (une capture de la ligne), ou None (LV1 cachée).
        Clic voulu (self.traverse) : relu dans l'image de la fenêtre LV1 si l'écran ne montre pas d'onglet."""
        xs = list(TABS.values())
        box = (min(xs), TAB_READ_Y, max(xs), TAB_READ_Y)

        def tab_in(read):
            found = [name for name, x in TABS.items() if _close(read(x, TAB_READ_Y), TAB_ACTIVE)]
            return found[0] if len(found) == 1 else None
        tab = tab_in(self.reader(box))
        if tab is None and self.traverse:
            r = self.window_reader(box)
            if r is not None:
                tab = tab_in(r)
                if tab is not None:
                    self.used_window = True
        return tab

    def on_mixer(self, frame, action):
        """Exécute action() sur la page Mixer. Si la LV1 est sur l'onglet Channel (sélection très utile là,
        demande de Joseph) : clic Mixer N, attente qu'il soit affiché, vérification de la case, action, puis
        retour sur Channel. Renvoie (fait, raison)."""
        hop = not self.detached and self.active_tab() == "Channel"
        if hop:
            self.click(TABS["Mixer %d" % self.mixer], TAB_Y)
            t_end = time.time() + HOP_WAIT
            while self.active_tab() != "Mixer %d" % self.mixer:
                if time.time() > t_end:
                    self.click(TABS["Channel"], TAB_Y)
                    return False, "onglet Mixer %d pas affiché après le clic" % self.mixer
                time.sleep(0.02)
            t_end = time.time() + REDRAW_WAIT             # page pas encore redessinée : on relit un moment
            why = self.frame_why(frame)
            while why and time.time() < t_end:
                time.sleep(0.03)
                why = self.frame_why(frame)
            if why:
                self.click(TABS["Channel"], TAB_Y)
                return False, "page Mixer : %s" % why
        ok = action()
        if hop:
            # action refusée faute de dessin, sans rien avoir cliqué (`action.retry`, ex. bande du nom introuvable) :
            # on réessaie pendant le redessin
            t_end = time.time() + REDRAW_WAIT
            while not ok and getattr(action, "retry", False) and time.time() < t_end:
                time.sleep(0.03)
                ok = action()
            time.sleep(0.08)
            self.click(TABS["Channel"], TAB_Y)
        return ok, None

    def click(self, rx, ry, method="message"):
        cx, cy = self.pt(rx, ry)
        if method == "souris":
            return self._click_mouse(*self.screen(rx, ry))
        u = u32()
        # fenêtre enfant la plus profonde sous le point (coordonnées client de chaque niveau)
        h, p = self.hwnd, wt.POINT(cx, cy)
        while True:
            child = u.ChildWindowFromPointEx(h, p, 0x0001 | 0x0004)   # CWP_SKIPINVISIBLE | SKIPTRANSPARENT
            if not child or child == h:
                break
            sp = wt.POINT(p.x, p.y)
            u.ClientToScreen(h, ctypes.byref(sp))
            u.ScreenToClient(child, ctypes.byref(sp))
            h, p = child, sp
        lp = (p.y & 0xFFFF) << 16 | (p.x & 0xFFFF)
        ok = (u.PostMessageW(h, WM_MOUSEMOVE, 0, lp) and u.PostMessageW(h, WM_LBUTTONDOWN, MK_LBUTTON, lp))
        time.sleep(0.05)
        ok = ok and u.PostMessageW(h, WM_LBUTTONUP, 0, lp)
        return bool(ok)

    def wheel(self, rx, ry, notches, method="message"):
        """Crans de molette au point (rx, ry) : message WM_MOUSEWHEEL à la fenêtre (souris immobile), ou
        « souris » : le pointeur va au-dessus, molette, puis revient (secours si la LV1 ignore le message)."""
        sx, sy = self.screen(rx, ry)
        delta = int(notches) * WHEEL_DELTA
        if method == "souris":
            u = u32()
            old = wt.POINT()
            u.GetCursorPos(ctypes.byref(old))
            u.SetCursorPos(sx, sy)
            u.mouse_event(0x0800, 0, 0, ctypes.c_ulong(delta & 0xFFFFFFFF).value, 0)   # MOUSEEVENTF_WHEEL
            time.sleep(0.01)
            u.SetCursorPos(old.x, old.y)
            return True
        u = u32()
        cx, cy = self.pt(rx, ry)
        h, p = self.hwnd, wt.POINT(cx, cy)
        while True:
            child = u.ChildWindowFromPointEx(h, p, 0x0001 | 0x0004)
            if not child or child == h:
                break
            sp = wt.POINT(p.x, p.y)
            u.ClientToScreen(h, ctypes.byref(sp))
            u.ScreenToClient(child, ctypes.byref(sp))
            h, p = child, sp
        wparam = (delta & 0xFFFF) << 16
        lparam = (sy & 0xFFFF) << 16 | (sx & 0xFFFF)          # WM_MOUSEWHEEL : coordonnées ÉCRAN
        lpm = (p.y & 0xFFFF) << 16 | (p.x & 0xFFFF)
        u.PostMessageW(h, WM_MOUSEMOVE, 0, lpm)
        return bool(u.PostMessageW(h, 0x020A, wparam, lparam))

    def _click_mouse(self, sx, sy):
        u = u32()
        if u.GetForegroundWindow() != self.hwnd:
            return False
        old = wt.POINT()
        u.GetCursorPos(ctypes.byref(old))
        u.SetCursorPos(sx, sy)
        u.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.05)
        u.SetCursorPos(old.x, old.y)
        return True


# Tranche sélectionnée sur la LV1 (sens LV1 -> X-Touch) : liseré jaune pur en haut de sa case de source, présent
# dans tous les modes (relevé par x32-gain-recall, `lv1_selected_column_top`, et sur la capture du 14/10).


def yellow_column(rows, w):
    """Colonne 0..15 du liseré jaune dans des lignes de pixels [(r, g, b)...] de largeur w (référence
    1920 mise à l'échelle), ou None (aucune, ou ambigu)."""
    for row in rows:
        cols, start = set(), None
        for i, c in enumerate(list(row) + [(0, 0, 0)]):
            yel = _close(c, SEL_YELLOW, 6)
            if yel and start is None:
                start = i
            elif not yel and start is not None:
                if i - start >= 0.03 * w:
                    k = int((start * REF_W / w - SEL_X0) / SEL_PITCH + 0.02)
                    if 0 <= k < 16:
                        cols.add(k)
                start = None
        if len(cols) == 1:
            return cols.pop()
    return None


def selected_strip(mixer=1):
    """Tranche 0..15 sélectionnée sur la LV1 (lue à l'écran), ou (None, raison). Pas besoin d'administrateur."""
    t = Target(mixer)
    if not t.hwnd or not t.rect or u32().IsIconic(t.hwnd) or t.rect[2] < 800:
        return None, "LV1 introuvable ou réduite"
    if not t.detached and t.active_tab() != "Mixer %d" % mixer:
        return None, "onglet Mixer %d pas affiché" % mixer
    x, y, w, h = t.rect
    rows = screen_rows(x, [y + round(h * r / REF_H) for r in SEL_TOP_ROWS], w)
    return yellow_column(rows, w), None


# Page Channel : quand on touche un potard de plugin, son réglage apparaît en bas en fader horizontal
# (« Comp Attack 6.91 », capture du 15/10). La molette de la souris au-dessus le fait bouger (essai de Joseph ;
# pas le clavier). Piste grise (54, 54, 54) x 690..1572, y 1040..1049 ; poignée claire (231, 231, 231).
WHEEL_DELTA = 120


def bottom_fader_ok(read):
    """Vrai si la piste du fader horizontal du bas est visible : gris aux 2 bouts et au milieu (poignée exceptée)."""
    xs = (BOTTOM_X[0] + 8, (BOTTOM_X[0] + BOTTOM_X[1]) // 2, BOTTOM_X[1] - 8)
    hits = [_close(read(x, BOTTOM_Y), BOTTOM_GREY, 10) for x in xs]
    return sum(hits) >= 2                  # la poignée peut cacher un des trois points


def jog_bottom_fader(notches, mixer=1, method="message"):
    """Jog wheel (demande de Joseph) : `notches` crans de molette sur le fader horizontal du bas de la page
    Channel (réglage du potard de plugin sélectionné). Renvoie (fait, raison)."""
    t = Target(mixer)
    if not is_admin():
        return False, "pas administrateur"
    if not t.hwnd or not t.rect or u32().IsIconic(t.hwnd):
        return False, "LV1 introuvable ou réduite"
    tab = t.active_tab()
    if tab != "Channel":
        return False, "onglet Channel pas affiché (lu : %s)" % tab
    if not bottom_fader_ok(lambda x, y: pixel(*t.screen(x, y))):
        return False, "pas de fader de plugin en bas (toucher d'abord un potard du plugin)"
    return t.wheel((BOTTOM_X[0] + BOTTOM_X[1]) // 2, BOTTOM_Y, notches, method), None


def layer_point(k):
    return LAYER_X, LAYER_Y0 + LAYER_PITCH * k


def layer_edge_why(read, k):
    """Garde-fou d'une case de couche : son bord gauche (x 1782..1789) doit être clair — contour gris (160) si inactive,
    rempli de bleu (Input / Factory / Mix) ou de violet (Custom) si active ; fond de colonne (71) sinon.
    Avant (16/10) : un point de l'aperçu gris intérieur (x 1795), absent des pages Custom vides -> clic refusé."""
    y = LAYER_Y0 + LAYER_PITCH * k
    if any((c := read(x, y)) and sum(c) >= 300 for x in range(LAYER_EDGE[0], LAYER_EDGE[1] + 1)):
        return None
    return "bord de la case de couche %d introuvable (x %d..%d, y %d)" % (k + 1, LAYER_EDGE[0], LAYER_EDGE[1], y)


def layer_frame(k):
    """Garde-fou de la case k pour Target.check / on_mixer (fonction de la cible ; une capture du bord)."""
    y = LAYER_Y0 + LAYER_PITCH * k
    return lambda t: t.guard((LAYER_EDGE[0], y, LAYER_EDGE[1], y), lambda r: layer_edge_why(r, k))


def strip_point(i):
    return STRIP_X0 + STRIP_PITCH * i, STRIP_NAME_Y


# Bande du nom de tranche : sa position dépend des modes Top / Middle / Bottom / Big Fader (question de Joseph,
# 14/10). On la CHERCHE dans la colonne de la tranche : pixels de la couleur exacte du canal (/Notify/TrackColor),
# hauteur 12..34 px sur 1080, entre y 300 et 700 (la case de source en haut et le pied de tranche ont aussi la
# couleur du canal, mais hors de cette plage ou d'une autre hauteur). Introuvable = pas de clic.


def name_bar_y(runs, ref_y=STRIP_NAME_Y):
    """Parmi des bandes (y0, y1) en coordonnées de référence, celle du nom : hauteur plausible, la plus proche
    de la position habituelle. Renvoie son centre, ou None."""
    ok = [(y0, y1) for y0, y1 in runs if NAME_H[0] <= y1 - y0 + 1 <= NAME_H[1]]
    if not ok:
        return None
    y0, y1 = min(ok, key=lambda r: abs((r[0] + r[1]) / 2.0 - ref_y))
    return (y0 + y1) / 2.0


def color_runs(colors, rgb, y0, tol=14):
    """Bandes consécutives de la couleur rgb dans une colonne de pixels commençant à y0."""
    runs, start = [], None
    for k, c in enumerate(list(colors) + [None]):
        hit = c is not None and _close(c, rgb, tol)
        if hit and start is None:
            start = k
        elif not hit and start is not None:
            runs.append((y0 + start, y0 + k - 1))
            start = None
    merged = []                      # recolle les morceaux coupés par le texte du nom (écart < 10 px)
    for r in runs:
        if merged and r[0] - merged[-1][1] <= 10:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    return merged


def _vu(t, res):
    """(fait, raison) d'un clic : sur un succès décidé dans l'image de la fenêtre, la raison le dit (journal)."""
    ok, why = res
    return ok, why or ("vu à travers la fenêtre qui couvre la LV1" if ok and t.used_window else None)


def click_layer(k, mixer=1, method="message"):
    """Clique la case de couche k (0..7). Renvoie (fait, raison)."""
    t = Target(mixer)
    t.traverse = True
    why = t.check(layer_frame(k))
    if why:
        return False, why
    return _vu(t, t.on_mixer(layer_frame(k), lambda: t.click(*layer_point(k), method=method)))


def mode_row_why(read):
    """Garde-fou des boutons de mode : la rangée Custom / Spill doit montrer, dans chacun des deux boutons, du texte ou
    un fond de bouton actif — somme RVB >= 300 : texte (≥ 600), bleu actif (512), violet de Custom actif (413), contour
    gris (480) ; le fond de la colonne (71 -> 213) et l'intérieur sombre (17) ne comptent pas. 2e essai du 16/10 : seuil
    450 -> Custom / Spill ACTIFS non reconnus (violet), plus aucun clic de mode ensuite."""
    for x0, x1 in MODE_SPANS:
        hits = sum(1 for x in range(x0, x1 + 1, 2) if (c := read(x, MODE_ROW_Y)) and sum(c) >= 300)
        if hits < 3:
            return "boutons Custom / Spill introuvables en y %d (x %d..%d)" % (MODE_ROW_Y, x0, x1)
    return None


def mode_guard_why(read):
    """Page Mixer reconnue pour un clic de mode : rangée Custom / Spill OU bord de la 1re case de couche (au cas où un
    mode actif dessinerait ses boutons d'une couleur pas encore vue). Rien des deux -> pas de clic."""
    row = mode_row_why(read)
    return row if (row and layer_edge_why(read, 0)) else None


def click_mode(name, n_inputs, mixer=1, method="message"):
    """Clique le bouton de mode de couche `name` (input, mix, factory, custom, spill) ; n_inputs = configuration de la
    LV1 (80 : Input / Mix ; sinon Factory). Input / Mix / Factory : un clic active ; Custom / Spill : bascules de la
    LV1 (un 2e clic revient au dernier Input / Mix). Renvoie (fait, raison)."""
    if name not in (MODES_80 if n_inputs == 80 else MODES_64):
        return False, "pas de bouton %s en %s canaux" % (name, n_inputs or "?")
    t = Target(mixer)
    t.traverse = True
    row = lambda tg: tg.guard((LAYER_EDGE[0], MODE_ROW_Y, MODE_SPANS[1][1], LAYER_Y0), mode_guard_why)
    why = t.check(row)
    if why:
        return False, why
    return _vu(t, t.on_mixer(row, lambda: t.click(*MODE_BUTTONS[name], method=method)))


def view_hint():
    """Pour suivre le Mixer affiché : (onglet actif de la fenêtre PRINCIPALE ou None, n° du Mixer détaché au premier plan
    ou None). Target(0) : il n'y a pas de fenêtre « MIXER0 », donc c'est la fenêtre principale."""
    from lv1 import screen
    u = u32()
    front = None
    fg = screen.foreground()
    if fg:
        title = screen.window_title(fg).upper().replace(" ", "")
        if title in ("MIXER1", "MIXER2"):
            front = int(title[-1])
    t = Target(0)
    tab = None
    if t.hwnd and t.rect and t.rect[2] >= 800 and not u.IsIconic(t.hwnd):
        tab = t.active_tab()
    return tab, front




def spill_on(mixer=1):
    """Spill allumé ? lu à l'écran (la base ne l'écrit pas : mode resté 4 avec Spill allumé, 16/10). None si la page
    Mixer N n'est pas affichée (onglet All, Channel, LV1 cachée) : le voyant garde alors son dernier état."""
    t = Target(mixer)
    if not t.hwnd or not t.rect or t.rect[2] < 800 or u32().IsIconic(t.hwnd):
        return None
    if not t.detached and t.active_tab() != "Mixer %d" % mixer:
        return None
    read = t.reader((1858, 479, 1900, 488))
    return sum(1 for p in SPILL_PTS if _close(read(*p), SPILL_ON, 20)) >= 2


def toggle_all_tab(mixer=1, method="message"):
    """Touche GLOBAL VIEW (Joseph, 16/10) : onglet All ; déjà sur All -> retour sur Mixer N. Renvoie (fait, raison)."""
    t = Target(mixer)
    t.traverse = True
    why = t.check(tabs=False)
    if why:
        return False, why
    if t.detached:
        return False, "Mixer détaché : pas d'onglet All dans cette fenêtre"
    tab = t.active_tab()
    if tab is None:
        return False, "onglets illisibles (LV1 cachée ?)"
    return _vu(t, (t.click(TABS["Mixer %d" % mixer if tab == "All" else "All"], TAB_Y, method), None))


def click_strip(i, mixer=1, method="message", rgb=None):
    """Clique le nom de la tranche i (0..15), cherché à l'écran par la couleur du canal rgb (0..255). Sans
    couleur connue, ou bande introuvable : pas de clic. Renvoie (fait, raison)."""
    if rgb is None:
        return False, "couleur du canal inconnue : bande du nom introuvable"
    t = Target(mixer)
    t.traverse = True
    why = t.check()
    if why:
        return False, why

    def act():
        x, y, w, h = t.rect
        sx = x + round((STRIP_X0 - 46 + NAME_DX + STRIP_PITCH * i) * w / REF_W)
        ya, yb = (y + round(v * h / REF_H) for v in NAME_SCAN)

        def bande(col):
            runs = [(round((a - y) * REF_H / h), round((b - y) * REF_H / h)) for a, b in color_runs(col, rgb, ya)]
            return name_bar_y(runs)
        ny = bande([row[0] for row in screen_rows(sx, list(range(ya, yb)), 1)])
        if ny is None and t.traverse:                     # une fenêtre couvre la tranche : relue dans la fenêtre LV1
            img = window_rows(t.hwnd, sx - x, list(range(ya - y, yb - y)), 1)
            if img:
                ny = bande([row[0] for row in img])
                if ny is not None:
                    t.used_window = True
        if ny is None:
            act.why = "bande du nom de la tranche %d introuvable (disposition Mixer ?)" % (i + 1)
            return False                                  # rien cliqué : réessayable (act.retry)
        act.why = None
        return t.click(strip_point(i)[0], ny, method=method)
    act.why, act.retry = None, True
    ok, why = _vu(t, t.on_mixer(None, act))
    return ok, why or act.why


def main(argv=None):
    ap = argparse.ArgumentParser(description="Clics simulés dans la LV1 (essai).")
    ap.add_argument("action", choices=["verifier", "couche", "tranche", "selection", "molette"])
    ap.add_argument("numero", nargs="?", type=int, help="couche 1..8 ou tranche 1..16")
    ap.add_argument("--mixer", type=int, choices=[1, 2], default=1)
    ap.add_argument("--methode", choices=["message", "souris"], default="message")
    ap.add_argument("--delai", type=float, default=3.0, help="attente avant le clic (s), le temps d'afficher la LV1")
    a = ap.parse_args(argv)
    t = Target(a.mixer)
    print("Administrateur : %s" % ("oui" if is_admin() else "NON"))
    print("Fenêtre LV1 : %s%s, zone client %s" % (t.hwnd, " (Mixer détaché)" if t.detached else "", t.rect))
    if a.action == "selection":
        col, why = selected_strip(a.mixer)
        print("Tranche sélectionnée sur la LV1 : %s" % (col + 1 if col is not None else (why or "aucune / illisible")))
        return 0
    if a.action == "verifier":
        print("Onglet affiché : %s" % (t.active_tab() if t.rect else "?"))
        for k in range(8):
            print("  couche %d -> %s : %s" % (k + 1, t.screen(*layer_point(k)) if t.rect else "?",
                                             t.check(layer_frame(k)) or "clic possible"))
        return 0
    if a.numero is None:
        ap.error("numéro manquant")
    print("Clic dans %.0f s : affiche la LV1 (page Mixer %d)…" % (a.delai, a.mixer))
    time.sleep(a.delai)
    if a.action == "molette":                       # numero = crans (négatif : vers le bas)
        ok, why = jog_bottom_fader(a.numero, a.mixer, a.methode)
    elif a.action == "couche":
        ok, why = click_layer(a.numero - 1, a.mixer, a.methode)
    else:
        ok, why = click_strip(a.numero - 1, a.mixer, a.methode)
    print("Clic envoyé." if ok else "Pas de clic : %s" % (why or "envoi refusé par Windows"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
