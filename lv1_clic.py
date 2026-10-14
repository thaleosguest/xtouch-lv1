#!/usr/bin/env python3
"""Clics simulés dans la fenêtre de la LV1 (couches, sélection) — l'API réseau n'a pas ces commandes.

Essai (hors concert), dans un PowerShell lancé EN ADMINISTRATEUR (la LV1 l'est : Windows refuse sinon) :
    py lv1_clic.py verifier            # ne clique pas : dit ce qui serait fait et pourquoi
    py lv1_clic.py couche 2            # clique la 2e case de couche (Ch 17-32 en usine)
    py lv1_clic.py tranche 5           # clique le nom de la tranche 5 (sélection)
    py lv1_clic.py selection           # lit à l'écran la tranche sélectionnée (sans clic, sans admin)
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

    def check(self, frame=None):
        """None si on peut cliquer, sinon la raison (texte)."""
        if not is_admin():
            return "pas administrateur (la LV1 l'est : Windows bloquerait le clic)"
        if not self.hwnd:
            return "fenêtre LV1 introuvable"
        if u32().IsIconic(self.hwnd):
            return "LV1 réduite"
        if not self.rect or self.rect[2] < 800:
            return "zone client LV1 illisible"
        if not self.detached:
            tab = self.active_tab()
            if tab not in ("Mixer %d" % self.mixer, "Channel"):
                return "onglet Mixer %d (ou Channel) pas affiché (lu : %s ; LV1 cachée ?)" % (self.mixer, tab)
            if tab == "Channel":
                return None            # aller-retour d'onglet : la case sera vérifiée sur la page Mixer
        if frame is not None:
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
            if frame is not None:
                c = pixel(*self.screen(*frame))
                if c is None or sum(c) < 150:
                    self.click(TABS["Channel"], TAB_Y)
                    return False, "case introuvable sur la page Mixer (couleur %s)" % (c,)
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


def layer_point(k):
    return LAYER_X, LAYER_Y0 + LAYER_PITCH * k


def layer_frame(k):
    return LAYER_FRAME_X, LAYER_Y0 + LAYER_PITCH * k


def strip_point(i):
    return STRIP_X0 + STRIP_PITCH * i, STRIP_NAME_Y


def click_layer(k, mixer=1, method="message"):
    """Clique la case de couche k (0..7). Renvoie (fait, raison)."""
    t = Target(mixer)
    why = t.check(layer_frame(k))
    if why:
        return False, why
    return t.on_mixer(layer_frame(k), lambda: t.click(*layer_point(k), method=method))


def click_strip(i, mixer=1, method="message"):
    """Clique le nom de la tranche i (0..15). Renvoie (fait, raison)."""
    t = Target(mixer)
    why = t.check()
    if why:
        return False, why
    return t.on_mixer(None, lambda: t.click(*strip_point(i), method=method))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Clics simulés dans la LV1 (essai).")
    ap.add_argument("action", choices=["verifier", "couche", "tranche", "selection"])
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
    if a.action == "couche":
        ok, why = click_layer(a.numero - 1, a.mixer, a.methode)
    else:
        ok, why = click_strip(a.numero - 1, a.mixer, a.methode)
    print("Clic envoyé." if ok else "Pas de clic : %s" % (why or "envoi refusé par Windows"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
