#!/usr/bin/env python3
"""Essai : piloter Tracks Live (Waves) par ses raccourcis clavier, envoyés à SA fenêtre (sans la mettre devant).

Tracks Live n'a ni MIDI, ni Mackie, ni OSC (son guide d'utilisation, 15/10/2026) : seuls ses raccourcis clavier
permettent de le piloter. On n'utilise que des touches SANS modificateur (un Ctrl envoyé par message n'est pas vu) :
    Espace = lecture / stop     /  = enregistrement      M = marqueur au curseur
    ;  ' = marqueur précédent / suivant      H / G = zoom avant / arrière      ← → = défilement d'une page
Méthode : PostMessage WM_KEYDOWN / WM_KEYUP à la fenêtre de Tracks Live (comme les clics dans la LV1). Si Tracks Live
est lancé en administrateur, ce programme doit l'être aussi (UIPI).

    py tracks_live.py verifier          # trouve la fenêtre de Tracks Live
    py tracks_live.py play | rec | marker | prev | next | zoomin | zoomout | gauche | droite   [--car | --devant]
    (--devant : Tracks Live passe au premier plan un instant, vraie touche tapée — Ctrl+R, Ctrl+Entrée —, puis retour)
    (--car : envoie le caractère seul, si la touche n'a pas d'effet)
Note : les touches « ; » et « ' » sont cherchées sur le clavier en cours (AZERTY compris).
"""
import ctypes
import ctypes.wintypes as wt
import sys

WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
# commande -> (code de touche virtuelle, caractère éventuel)
KEYS = {
    "play": (0x20, " "),           # Espace : lecture / stop
    "rec": (0x6F, "/"),            # / du pavé numérique (AZERTY : le « / » du clavier demande Maj)
    "marker": (0x4D, "m"),         # M : marqueur au curseur
    "prev": (0xBA, ";"),           # ; : marqueur précédent (clavier US ; voir note AZERTY plus bas)
    "next": (0xDE, "'"),           # ' : marqueur suivant
    "zoomin": (0x48, "h"),
    "zoomout": (0x47, "g"),
    "gauche": (0x25, None),
    "droite": (0x27, None),
}


def u32():
    u = ctypes.windll.user32
    vp = ctypes.c_void_p
    u.PostMessageW.argtypes = [vp, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    u.GetWindowThreadProcessId.argtypes = [vp, ctypes.POINTER(ctypes.c_ulong)]
    u.IsWindowVisible.argtypes = u.GetWindowTextLengthW.argtypes = [vp]
    u.GetWindowTextW.argtypes = [vp, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindow.argtypes = [vp, ctypes.c_uint]
    u.GetWindow.restype = vp
    u.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
    return u


def process_name(pid):
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wt.DWORD(520)
        k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle(h)


def find_window():
    """Fenêtre principale (visible, avec titre, sans propriétaire) du processus « Tracks Live.exe »."""
    u = u32()
    found = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(h, _):
        if u.IsWindowVisible(h) and not u.GetWindow(h, 4) and u.GetWindowTextLengthW(h):
            pid = ctypes.c_ulong(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if process_name(pid.value).lower() == "tracks live.exe":
                b = ctypes.create_unicode_buffer(256)
                u.GetWindowTextW(h, b, 256)
                rc = wt.RECT()
                u.GetWindowRect(ctypes.c_void_p(h), ctypes.byref(rc))
                found.append(((rc.right - rc.left) * (rc.bottom - rc.top), h, b.value))
        return True
    u.EnumWindows(proto(cb), 0)
    # la PLUS GRANDE : Tracks Live ouvre aussi des fenêtres « menu » (vu le 15/10), qui ne sont pas la principale
    return max(found)[1:] if found else (None, None)


def press(cmd, hwnd=None, method="touche"):
    """Envoie la touche de la commande à Tracks Live. Rend (ok, raison).
    method « touche » : WM_KEYDOWN / WM_KEYUP (Windows en déduit le caractère) ; « car » : WM_CHAR seul."""
    if cmd not in KEYS:
        return False, "commande inconnue"
    if hwnd is None:
        hwnd, _ = find_window()
    if not hwnd:
        return False, "fenêtre de Tracks Live introuvable"
    u = u32()
    vk, ch = KEYS[cmd]
    if ch:                       # touche du caractère sur le clavier EN COURS (AZERTY : « ; » n'est pas où il est en US)
        u.VkKeyScanW.argtypes = [ctypes.c_wchar]
        u.VkKeyScanW.restype = ctypes.c_short
        k = u.VkKeyScanW(ch)
        if k != -1 and not (k >> 8) & 0x07:       # accessible sans Maj / Ctrl / Alt
            vk = k & 0xFF
    scan = u.MapVirtualKeyW(vk, 0)
    ext = 1 << 24 if vk in (0x25, 0x27) else 0
    down = 1 | (scan << 16) | ext
    up = down | (1 << 30) | (1 << 31)
    if method == "car":
        if not ch:
            return False, "pas de caractère pour cette touche (méthode « car »)"
        ok = u.PostMessageW(hwnd, WM_CHAR, ord(ch), down)
    else:                        # PAS de WM_CHAR en plus : il serait reçu deux fois (Espace = lecture puis stop)
        ok = u.PostMessageW(hwnd, WM_KEYDOWN, vk, down) and u.PostMessageW(hwnd, WM_KEYUP, vk, up)
    return bool(ok), None if ok else "envoi refusé par Windows (Tracks Live en administrateur ?)"


# Méthode « devant » : Tracks Live ignore les touches envoyées à sa fenêtre (essais de Joseph du 15/10 : seul Espace
# a agi, sans doute en appuyant le bouton qui avait le focus). On le met donc au premier plan un instant, on tape la
# VRAIE touche (SendInput, modificateurs compris), puis on rend le premier plan à la fenêtre d'avant (la LV1).
VK_CTRL, VK_RETURN = 0x11, 0x0D
CHORDS = {
    "play": [0x20],                  # Espace
    "rec": [VK_CTRL, 0x52],          # Ctrl+R
    "marker": [VK_CTRL, VK_RETURN],  # Ctrl+Entrée
    "zoomin": [0x48], "zoomout": [0x47], "gauche": [0x25], "droite": [0x27],
}


def press_front(cmd, hwnd=None):
    import time
    if hwnd is None:
        hwnd, _ = find_window()
    if not hwnd:
        return False, "fenêtre de Tracks Live introuvable"
    keys = CHORDS.get(cmd)
    if keys is None and cmd in KEYS and KEYS[cmd][1]:          # ; et ' : touche du clavier en cours
        u = u32()
        u.VkKeyScanW.argtypes = [ctypes.c_wchar]
        u.VkKeyScanW.restype = ctypes.c_short
        k = u.VkKeyScanW(KEYS[cmd][1])
        keys = ([0x10] if (k >> 8) & 1 else []) + [k & 0xFF] if k != -1 else None
    if not keys:
        return False, "commande inconnue"
    u = u32()
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wt.DWORD, ctypes.c_size_t]
    before = u.GetForegroundWindow()
    focus(hwnd)
    t_end = time.time() + 0.3
    while u.GetForegroundWindow() != hwnd and time.time() < t_end:
        time.sleep(0.01)
    if u.GetForegroundWindow() != hwnd:
        return False, "Windows a refusé de mettre Tracks Live au premier plan"
    for vk in keys:
        u.keybd_event(vk, 0, 0, 0)
    for vk in reversed(keys):
        u.keybd_event(vk, 0, 2, 0)
    time.sleep(0.05)
    if before and before != hwnd:
        focus(before)
    return True, None


def focus(hwnd):
    """Premier plan à hwnd : on rattache un instant notre file d'entrée à celle de la fenêtre active, sinon Windows
    refuse (règle du « foreground lock »)."""
    u = u32()
    k = ctypes.windll.kernel32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.SetForegroundWindow.argtypes = u.BringWindowToTop.argtypes = [ctypes.c_void_p]
    u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    fg = u.GetForegroundWindow()
    me = k.GetCurrentThreadId()
    other = u.GetWindowThreadProcessId(fg, None) if fg else 0
    if other and other != me:
        u.AttachThreadInput(me, other, True)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if other and other != me:
            u.AttachThreadInput(me, other, False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verifier"
    h, title = find_window()
    if cmd == "verifier":
        print("Tracks Live :", "fenêtre %s « %s »" % (h, title) if h else "introuvable")
        sys.exit(0 if h else 1)
    if "--devant" in sys.argv:
        ok, why = press_front(cmd, h)
        print("%s -> Tracks Live (au premier plan un instant) : %s" % (cmd, "envoyé" if ok else why))
        sys.exit(0 if ok else 1)
    method = "car" if "--car" in sys.argv else "touche"
    ok, why = press(cmd, h, method)
    print("%s -> Tracks Live : %s" % (cmd, "envoyé" if ok else why))
