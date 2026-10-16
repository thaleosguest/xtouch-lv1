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

REF_W, REF_H = 1920.0, 1080.0
LAYER_X, LAYER_Y0, LAYER_PITCH, LAYER_FRAME_X = 1847, 537, 72, 1795
# Boutons de mode de couche, au-dessus des couches (captures du 16/10/2026, page Mixer 1, 1920x1080) : 80 canaux =
# Input + Mix ; 16 / 32 / 64 = un seul bouton Factory centré ; Custom et Spill partout. Colonne des couches identique
# dans les deux cas. Actif = rempli de bleu (56, 201, 255), inactif = fond sombre + texte clair : garde-fou = texte ou
# bleu présent dans les boutons Custom et Spill (mode_row_why ; 8 à 11 points clairs sur les captures, 0 ailleurs).
MODE_BUTTONS = {"input": (1814, 442), "mix": (1881, 442), "factory": (1847, 442), "custom": (1814, 479),
                "spill": (1881, 479)}
MODE_ROW_Y, MODE_SPANS = 479, ((1786, 1843), (1853, 1910))     # rangée Custom / Spill (garde-fou)
MODES_80 = ("input", "mix", "custom", "spill")
MODES_64 = ("factory", "custom", "spill")
STRIP_X0, STRIP_PITCH, STRIP_NAME_Y = 142 + 46, 96, 433
TAB_X = {1: 651, 2: 749}
TAB_Y = 28
TAB_ACTIVE = (56, 201, 255)
# Les 7 onglets (relevé du 14/10, capture lv1_channel) : centres x, couleur lue en y 14 (au-dessus du texte),
# actif = bleu, autres = gris clair (231, 231, 231). Clic au centre (y 28).
TABS = {"Mixer 1": 652, "Mixer 2": 750, "All": 848, "Channel": 946, "Show": 1044, "Patch": 1142, "Setup": 1240}
TAB_READ_Y = 14
HOP_WAIT = 0.6        # s max pour que la LV1 affiche l'onglet cliqué

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0200, 0x0201, 0x0202, 0x0001

_u32 = None


def u32():
    global _u32
    if _u32 is None:
        u = ctypes.windll.user32
        vp = ctypes.c_void_p
        u.IsWindowVisible.argtypes = u.IsIconic.argtypes = u.GetWindowTextLengthW.argtypes = [vp]
        u.GetWindowTextW.argtypes = [vp, ctypes.c_wchar_p, ctypes.c_int]
        u.GetWindow.argtypes = [vp, ctypes.c_uint]
        u.GetWindow.restype = vp
        u.GetClientRect.argtypes = u.ClientToScreen.argtypes = u.ScreenToClient.argtypes = [vp, vp]
        u.ChildWindowFromPointEx.argtypes = [vp, wt.POINT, ctypes.c_uint]
        u.ChildWindowFromPointEx.restype = vp
        u.PostMessageW.argtypes = [vp, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        u.GetDC.argtypes = [vp]
        u.GetDC.restype = vp
        u.ReleaseDC.argtypes = [vp, vp]
        u.GetForegroundWindow.restype = vp
        _u32 = u
    return _u32


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def lv1_window(mixer=1):
    """Fenêtre Mixer détachée (« MIXER1 »/« MIXER2 ») si elle existe, sinon la fenêtre principale."""
    u = u32()
    wins = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(h, _):
        if u.IsWindowVisible(h) and not u.GetWindow(h, 4):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                wins.append((h, b.value))
        return True
    u.EnumWindows(proto(cb), 0)
    for h, t in wins:
        if t.upper().replace(" ", "") == "MIXER%d" % mixer:
            return h, True
    for h, t in wins:
        if t.startswith("eMotion LV1"):
            return h, False
    return None, False


def client_rect(h):
    u = u32()
    r, pt = wt.RECT(), wt.POINT(0, 0)
    if not u.GetClientRect(h, ctypes.byref(r)) or not u.ClientToScreen(h, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def pixel(x, y):
    """Couleur d'un pixel de l'ÉCRAN (ce qui est vraiment affiché)."""
    g32 = ctypes.windll.gdi32
    g32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g32.GetPixel.restype = ctypes.c_uint32
    dc = u32().GetDC(None)
    try:
        c = g32.GetPixel(dc, x, y)
    finally:
        u32().ReleaseDC(None, dc)
    if c == 0xFFFFFFFF:
        return None
    return c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF


def _close(a, b, tol=12):
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


class Target:
    """Fenêtre LV1 + conversion des coordonnées de référence (1920x1080) en coordonnées client."""

    def __init__(self, mixer=1):
        self.mixer = mixer
        self.hwnd, self.detached = lv1_window(mixer)
        self.rect = client_rect(self.hwnd) if self.hwnd else None

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

    def active_tab(self):
        """Onglet affiché (« Mixer 1 », « Channel »…) lu à l'écran, ou None (LV1 cachée, illisible)."""
        found = [name for name, x in TABS.items() if _close(pixel(*self.screen(x, TAB_READ_Y)), TAB_ACTIVE)]
        return found[0] if len(found) == 1 else None

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
            why = self.frame_why(frame)
            if why:
                self.click(TABS["Channel"], TAB_Y)
                return False, "page Mixer : %s" % why
        ok = action()
        if hop:
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
SEL_TOP_ROWS = (98, 100, 102)      # /1080
SEL_YELLOW = (255, 242, 0)         # un canal de couleur jaune est (243, 250, 29) : distinct
SEL_X0, SEL_PITCH = 143, 96        # /1920


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


def screen_rows(x, ys, w):
    """Lignes d'écran ys (absolues), largeur w, en une capture GDI : [[(r, g, b)...] par ligne]."""
    g32, u = ctypes.windll.gdi32, u32()
    vp = ctypes.c_void_p
    for f in (g32.CreateCompatibleDC, g32.CreateCompatibleBitmap, g32.SelectObject):
        f.restype = vp
    g32.CreateCompatibleDC.argtypes = [vp]
    g32.CreateCompatibleBitmap.argtypes = [vp, ctypes.c_int, ctypes.c_int]
    g32.SelectObject.argtypes = [vp, vp]
    g32.BitBlt.argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, vp, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
    g32.GetDIBits.argtypes = [vp, vp, ctypes.c_uint, ctypes.c_uint, vp, vp, ctypes.c_uint]
    g32.DeleteObject.argtypes = g32.DeleteDC.argtypes = [vp]
    y0, h = min(ys), max(ys) - min(ys) + 1
    dc = u.GetDC(None)
    mem = g32.CreateCompatibleDC(dc)
    bmp = g32.CreateCompatibleBitmap(dc, w, h)
    old = g32.SelectObject(mem, bmp)
    try:
        g32.BitBlt(mem, 0, 0, w, h, dc, x, y0, 0x00CC0020)
        bmi = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = (ctypes.c_ubyte * (4 * w * h))()
        g32.GetDIBits(mem, bmp, 0, h, buf, bmi, 0)
    finally:
        g32.SelectObject(mem, old)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mem)
        u.ReleaseDC(None, dc)
    out = []
    for yy in ys:
        o = 4 * (yy - y0) * w
        out.append([(buf[o + 4 * i + 2], buf[o + 4 * i + 1], buf[o + 4 * i]) for i in range(w)])
    return out


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
BOTTOM_Y = 1044
BOTTOM_X = (690, 1572)
BOTTOM_GREY = (54, 54, 54)
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


def layer_frame(k):
    return LAYER_FRAME_X, LAYER_Y0 + LAYER_PITCH * k


def strip_point(i):
    return STRIP_X0 + STRIP_PITCH * i, STRIP_NAME_Y


# Bande du nom de tranche : sa position dépend des modes Top / Middle / Bottom / Big Fader (question de Joseph,
# 14/10). On la CHERCHE dans la colonne de la tranche : pixels de la couleur exacte du canal (/Notify/TrackColor),
# hauteur 12..34 px sur 1080, entre y 300 et 700 (la case de source en haut et le pied de tranche ont aussi la
# couleur du canal, mais hors de cette plage ou d'une autre hauteur). Introuvable = pas de clic.
NAME_SCAN = (300, 700)
NAME_H = (12, 34)
NAME_DX = 3                      # colonne lue : 3 px après le bord gauche de la bande (le texte n'y arrive pas)


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


def click_layer(k, mixer=1, method="message"):
    """Clique la case de couche k (0..7). Renvoie (fait, raison)."""
    t = Target(mixer)
    why = t.check(layer_frame(k))
    if why:
        return False, why
    return t.on_mixer(layer_frame(k), lambda: t.click(*layer_point(k), method=method))


def mode_row_why(read):
    """Garde-fou des boutons de mode : la rangée Custom / Spill doit montrer du texte ou un fond bleu (pixels clairs)
    dans chacun des deux boutons. Le cadre des couches ne convient pas : en mode Custom la colonne des couches change
    d'allure (journal du 16/10 : (1795, 537) sombre -> plus aucun clic de mode, Custom « bloqué »)."""
    for x0, x1 in MODE_SPANS:
        hits = sum(1 for x in range(x0, x1 + 1, 2) if (c := read(x, MODE_ROW_Y)) and sum(c) >= 450)
        if hits < 3:
            return "boutons Custom / Spill introuvables en y %d (x %d..%d)" % (MODE_ROW_Y, x0, x1)
    return None


def click_mode(name, n_inputs, mixer=1, method="message"):
    """Clique le bouton de mode de couche `name` (input, mix, factory, custom, spill) ; n_inputs = configuration de la
    LV1 (80 : Input / Mix ; sinon Factory). Input / Mix / Factory : un clic active ; Custom / Spill : bascules de la
    LV1 (un 2e clic revient au dernier Input / Mix). Renvoie (fait, raison)."""
    if name not in (MODES_80 if n_inputs == 80 else MODES_64):
        return False, "pas de bouton %s en %s canaux" % (name, n_inputs or "?")
    t = Target(mixer)
    row = lambda tg: mode_row_why(lambda x, y: pixel(*tg.screen(x, y)))
    why = t.check(row)
    if why:
        return False, why
    return t.on_mixer(row, lambda: t.click(*MODE_BUTTONS[name], method=method))


def toggle_all_tab(mixer=1, method="message"):
    """Touche GLOBAL VIEW (Joseph, 16/10) : onglet All ; déjà sur All -> retour sur Mixer N. Renvoie (fait, raison)."""
    t = Target(mixer)
    why = t.check(tabs=False)
    if why:
        return False, why
    if t.detached:
        return False, "Mixer détaché : pas d'onglet All dans cette fenêtre"
    tab = t.active_tab()
    if tab is None:
        return False, "onglets illisibles (LV1 cachée ?)"
    return t.click(TABS["Mixer %d" % mixer if tab == "All" else "All"], TAB_Y, method), None


def click_strip(i, mixer=1, method="message", rgb=None):
    """Clique le nom de la tranche i (0..15), cherché à l'écran par la couleur du canal rgb (0..255). Sans
    couleur connue, ou bande introuvable : pas de clic. Renvoie (fait, raison)."""
    if rgb is None:
        return False, "couleur du canal inconnue : bande du nom introuvable"
    t = Target(mixer)
    why = t.check()
    if why:
        return False, why

    def act():
        x, y, w, h = t.rect
        sx = x + round((STRIP_X0 - 46 + NAME_DX + STRIP_PITCH * i) * w / REF_W)
        ya, yb = (y + round(v * h / REF_H) for v in NAME_SCAN)
        col = [row[0] for row in screen_rows(sx, list(range(ya, yb)), 1)]
        runs = [(round((a - y) * REF_H / h), round((b - y) * REF_H / h)) for a, b in color_runs(col, rgb, ya)]
        ny = name_bar_y(runs)
        if ny is None:
            act.why = "bande du nom de la tranche %d introuvable (disposition Mixer ?)" % (i + 1)
            return False
        return t.click(strip_point(i)[0], ny, method=method)
    act.why = None
    ok, why = t.on_mixer(None, act)
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
