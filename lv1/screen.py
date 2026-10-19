"""Fenêtres Windows et lecture de l'écran, en un seul endroit (étape 4 du refactor, 19/10/2026).

Avant, ce code existait en plusieurs exemplaires :
  - deux réglages de user32 (`lv1_clic.u32` et `fenetres._u32`) qui modifiaient LE MÊME objet partagé
    (`ctypes.windll.user32`) : identiques là où ils se recoupaient (vérifié le 19/10), mais le premier qui aurait
    divergé aurait changé le comportement de l'autre ;
  - le n° de processus d'une fenêtre en 2 copies (`fenetres.pid_of`, `xtouch_overlay_qt.window_pid`) ;
  - la fenêtre au premier plan lue de 3 façons (`fenetres`, overlay Qt, `lv1_clic.view_hint`).
Le code est déplacé tel quel ; les anciens noms sont réexportés par leurs modules d'origine.

Rien ici ne clique (les clics restent dans `lv1_clic`) et rien ne dépend de Qt. Tout est en ctypes.
Restent à part, volontairement : la capture de `lv1_patch` (PrintWindow : photographie la fenêtre LV1 même
cachée, une autre technique) et `tracks_live.py` (essai autonome du 15/10, utilisé par rien).
"""
import ctypes
from ctypes import wintypes as wt

_u32 = None


def user32():
    """user32 avec ses types d'arguments posés UNE fois (handles 64 bits : sans argtypes, ctypes les tronque).
    Réunion des réglages de lv1_clic.u32 (fenêtres, zone client, clics) et de fenetres._u32 (premier plan)."""
    global _u32
    if _u32 is None:
        u = ctypes.windll.user32
        vp = ctypes.c_void_p
        # ── d'après lv1_clic.u32
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
        # ── d'après fenetres._u32
        u.GetWindowThreadProcessId.argtypes = [vp, ctypes.POINTER(ctypes.c_ulong)]
        u.GetWindowThreadProcessId.restype = wt.DWORD
        u.SetForegroundWindow.argtypes = u.BringWindowToTop.argtypes = [vp]
        u.ShowWindow.argtypes = [vp, ctypes.c_int]
        u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        u.GetWindowRect.argtypes = [vp, ctypes.POINTER(wt.RECT)]
        _u32 = u
    return _u32


# ── fenêtres ──────────────────────────────────────────────────────────────────────────────────────────────────

def windows():
    """Fenêtres de premier niveau visibles, avec un titre et sans propriétaire : [(hwnd, titre)], dans l'ordre de
    Windows (du dessus vers le dessous). Même filtre que lv1_clic.lv1_window et fenetres.main_window avant."""
    u = user32()
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
    return wins


def window_title(hwnd):
    """Titre d'une fenêtre ("" si aucun)."""
    u = user32()
    n = u.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def window_pid(hwnd):
    """N° du processus propriétaire d'une fenêtre."""
    pid = ctypes.c_ulong(0)
    user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def exe_of(pid):
    """Nom du programme d'un processus, en minuscules (« reaper.exe »), ou "" si illisible."""
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(520), wt.DWORD(520)
        return buf.value.rsplit("\\", 1)[-1].lower() if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k.CloseHandle(h)


def foreground():
    """Fenêtre au premier plan (handle), ou None."""
    return user32().GetForegroundWindow() or None


def foreground_pid():
    """Processus de la fenêtre au premier plan (0 si inconnu)."""
    h = foreground()
    return window_pid(h) if h else 0


def lv1_window(mixer=1):
    """Fenêtre Mixer détachée (« MIXER1 »/« MIXER2 ») si elle existe, sinon la fenêtre principale."""
    wins = windows()
    for h, t in wins:
        if t.upper().replace(" ", "") == "MIXER%d" % mixer:
            return h, True
    for h, t in wins:
        if t.startswith("eMotion LV1"):
            return h, False
    return None, False


def client_rect(h):
    """Zone client d'une fenêtre en coordonnées écran : (x, y, largeur, hauteur), ou None."""
    u = user32()
    r, pt = wt.RECT(), wt.POINT(0, 0)
    if not u.GetClientRect(h, ctypes.byref(r)) or not u.ClientToScreen(h, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


# ── écran ─────────────────────────────────────────────────────────────────────────────────────────────────────

def pixel(x, y):
    """Couleur d'un pixel de l'ÉCRAN (ce qui est vraiment affiché). 15-30 ms par point : pour une zone, screen_rows."""
    g32 = ctypes.windll.gdi32
    g32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g32.GetPixel.restype = ctypes.c_uint32
    dc = user32().GetDC(None)
    try:
        c = g32.GetPixel(dc, x, y)
    finally:
        user32().ReleaseDC(None, dc)
    if c == 0xFFFFFFFF:
        return None
    return c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF


def screen_rows(x, ys, w):
    """Lignes d'écran ys (absolues), largeur w, en une capture GDI : [[(r, g, b)...] par ligne]."""
    g32, u = ctypes.windll.gdi32, user32()
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


def close(a, b, tol=12):
    """Deux couleurs à tol près sur chaque composante (a = None, couleur illisible : jamais proche)."""
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))
