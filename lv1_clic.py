#!/usr/bin/env python3
"""Clics simulés dans la fenêtre de la LV1 (couches, sélection) — l'API réseau n'a pas ces commandes.

Essai (hors concert), dans un PowerShell lancé EN ADMINISTRATEUR (la LV1 l'est : Windows refuse sinon) :
    py lv1_clic.py verifier            # ne clique pas : dit ce qui serait fait et pourquoi
    py lv1_clic.py couche 2            # clique la 2e case de couche (Ch 17-32 en usine)
    py lv1_clic.py tranche 5           # clique le nom de la tranche 5 (sélection ?)
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
            c = pixel(*self.screen(TAB_X[self.mixer], TAB_Y))
            if not _close(c, TAB_ACTIVE):
                return "onglet Mixer %d pas affiché (couleur lue %s ; LV1 cachée ou autre page ?)" % (self.mixer, c)
        if frame is not None:
            c = pixel(*self.screen(*frame))
            if c is None or sum(c) < 150:
                return "cadre de la case attendu en %s introuvable (couleur %s)" % (frame, c)
        return None

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
    return t.click(*layer_point(k), method=method), None


def click_strip(i, mixer=1, method="message"):
    """Clique le nom de la tranche i (0..15). Renvoie (fait, raison)."""
    t = Target(mixer)
    why = t.check()
    if why:
        return False, why
    return t.click(*strip_point(i), method=method), None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Clics simulés dans la LV1 (essai).")
    ap.add_argument("action", choices=["verifier", "couche", "tranche"])
    ap.add_argument("numero", nargs="?", type=int, help="couche 1..8 ou tranche 1..16")
    ap.add_argument("--mixer", type=int, choices=[1, 2], default=1)
    ap.add_argument("--methode", choices=["message", "souris"], default="message")
    ap.add_argument("--delai", type=float, default=3.0, help="attente avant le clic (s), le temps d'afficher la LV1")
    a = ap.parse_args(argv)
    t = Target(a.mixer)
    print("Administrateur : %s" % ("oui" if is_admin() else "NON"))
    print("Fenêtre LV1 : %s%s, zone client %s" % (t.hwnd, " (Mixer détaché)" if t.detached else "", t.rect))
    if a.action == "verifier":
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
