#!/usr/bin/env python3
"""Fenêtres Windows : quelle application est au premier plan, et mettre la LV1 ou Reaper devant (demande de Joseph du
15/10/2026 : un bouton de la X-Touch bascule entre Reaper et la LV1, et SAVE agit selon la fenêtre active).

    py fenetres.py              # affiche l'application au premier plan (lv1 / reaper / autre)
    py fenetres.py reaper|lv1   # met cette application au premier plan
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

REAPER_EXE = "reaper.exe"


from lv1.screen import user32 as _u32, window_pid as pid_of, exe_of, windows, lv1_window   # étape 4


def lv1_hwnd(mixer=1):
    h, _ = lv1_window(mixer)
    return h


def main_window(exe):
    """Plus grande fenêtre visible, avec titre et sans propriétaire, du programme exe (ex. reaper.exe)."""
    u = _u32()
    found = []
    for h, _titre in windows():                       # visibles, avec titre, sans propriétaire (même filtre qu'avant)
        if exe_of(pid_of(h)) == exe:
            rc = wt.RECT()
            u.GetWindowRect(h, ctypes.byref(rc))
            found.append(((rc.right - rc.left) * (rc.bottom - rc.top), h))
    return max(found)[1] if found else None


def front_app(mixer=1):
    """« lv1 », « reaper » ou « autre » selon la fenêtre au premier plan (fenêtres secondaires comprises)."""
    try:
        fg = _u32().GetForegroundWindow()
        if not fg:
            return "autre"
        pid = pid_of(fg)
        lv1 = lv1_hwnd(mixer)
        if lv1 and pid == pid_of(lv1):
            return "lv1"
        return "reaper" if exe_of(pid) == REAPER_EXE else "autre"
    except Exception:
        return "autre"


def focus(hwnd):
    """Met hwnd au premier plan (rattache un instant notre file d'entrée à celle de la fenêtre active, sinon Windows
    refuse : « foreground lock ») ; la restaure si elle est réduite."""
    if not hwnd:
        return False
    u = _u32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                         # SW_RESTORE
    fg = u.GetForegroundWindow()
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    other = u.GetWindowThreadProcessId(fg, None) if fg else 0
    if other and other != me:
        u.AttachThreadInput(me, other, True)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if other and other != me:
            u.AttachThreadInput(me, other, False)
    return u.GetForegroundWindow() == hwnd


def bring(app, mixer=1):
    return focus(lv1_hwnd(mixer) if app == "lv1" else main_window(REAPER_EXE))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(sys.argv[1], "au premier plan :", bring(sys.argv[1]))
    else:
        print("premier plan :", front_app())
