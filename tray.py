"""(Copie de x32-gain-recall/tray.py, même auteur.) Icône dans la zone de notification de Windows (près de l'horloge), en ctypes pur (pas de pystray / Pillow).

Remplace la fenêtre noire de l'appli depuis la 2.3.0 (exe compilé sans console) : clic droit = menu
(entrées fournies par l'appelant, cochables), double-clic = action par défaut. Tourne sur son propre
thread (fenêtre cachée + boucle de messages Windows) ; les actions sont appelées sur ce thread.
"""

import ctypes
import os
import sys
import threading
from ctypes import wintypes

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_APP_TRAY = 0x8000 + 1                        # WM_APP + 1 : message de rappel de l'icône
WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0203, 0x0205
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
MF_STRING, MF_CHECKED, MF_GRAYED, MF_SEPARATOR = 0x0, 0x8, 0x1, 0x800
TPM_RETURNCMD, TPM_NONOTIFY, TPM_RIGHTBUTTON = 0x0100, 0x0080, 0x0002

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


def _api():
    u32, sh32, k32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
    u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.DefWindowProcW.restype = LRESULT
    u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.CreatePopupMenu.restype = wintypes.HMENU
    u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.LPVOID]
    u32.DestroyMenu.argtypes = [wintypes.HMENU]
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.DestroyWindow.argtypes = [wintypes.HWND]
    u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u32.DispatchMessageW.restype = LRESULT
    u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                               wintypes.UINT]
    u32.LoadImageW.restype = wintypes.HANDLE
    u32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    u32.LoadIconW.restype = wintypes.HICON
    u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    sh32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    sh32.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT]
    sh32.ExtractIconW.restype = wintypes.HICON
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    return u32, sh32, k32


class TrayIcon:
    """items : liste de (libellé, action) ou None (séparateur) ; libellé peut être une fonction (texte
    recalculé à chaque ouverture du menu) ; action = fonction sans argument. checked : {libellé: fonction
    -> bool} pour les entrées cochables. La 1re entrée est l'action par défaut (double-clic, en gras)."""

    def __init__(self, tooltip, items, checked=None, icon_path=None):
        self.tooltip = tooltip[:127]
        self.items = items
        self.checked = checked or {}
        self.icon_path = icon_path
        self.hwnd = None
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        if sys.platform != "win32":
            return self
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        return self

    def notify(self, title, text):
        """Bulle de notification Windows (une fois, ex. mise à jour disponible)."""
        if not self.hwnd:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = 1                       # NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # -- thread de l'icône ------------------------------------------------
    def _load_icon(self, u32, sh32, hinst):
        if getattr(sys, "frozen", False):
            h = sh32.ExtractIconW(hinst, sys.executable, 0)       # icône intégrée à l'exe (--icon)
            if h and h > 1:
                return h
        if self.icon_path and os.path.exists(self.icon_path):
            h = u32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10 | 0x40)   # IMAGE_ICON, LOADFROMFILE|DEFAULTSIZE
            if h:
                return h
        return u32.LoadIconW(None, ctypes.c_void_p(32512))            # IDI_APPLICATION

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tooltip
        return nid

    def _run(self):
        try:
            u32, sh32, k32 = _api()
            hinst = k32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._proc)        # garder une référence : sinon le rappel est libéré
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = "XM32GainRecallTray"
            u32.RegisterClassW(ctypes.byref(wc))
            self._taskbar_created = u32.RegisterWindowMessageW("TaskbarCreated")
            self.hwnd = u32.CreateWindowExW(0, wc.lpszClassName, "XM32 Gain Recall", 0, 0, 0, 0, 0,
                                            None, None, hinst, None)
            self._hicon = self._load_icon(u32, sh32, hinst)
            sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid()))
        except Exception as e:
            print("Icone de notification impossible : %s" % e)
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    def _label(self, label):
        return label() if callable(label) else label

    def _menu(self):
        u32 = ctypes.windll.user32
        hmenu = u32.CreatePopupMenu()
        for n, item in enumerate(self.items):
            if item is None:
                u32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            label, _action = item
            text = self._label(label)
            if text is None:                 # entrée masquée pour l'instant (ex. pas de mise à jour)
                continue
            flags = MF_STRING
            check = self.checked.get(label)
            if check is not None:
                try:
                    flags |= MF_CHECKED if check() else 0
                except Exception:
                    pass
            u32.AppendMenuW(hmenu, flags, n + 1, text)
        u32.SetMenuDefaultItem(hmenu, 1, 0)
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(self.hwnd)       # sinon le menu ne se ferme pas en cliquant ailleurs
        cmd = u32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON, pt.x, pt.y, 0,
                                 self.hwnd, None)
        u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u32.DestroyMenu(hmenu)
        if cmd:
            self._do(cmd - 1)

    def _do(self, n):
        item = self.items[n] if 0 <= n < len(self.items) else None
        if item:
            try:
                item[1]()
            except Exception as e:
                print("Action de l'icone : %s" % e)

    def _proc(self, hwnd, msg, wparam, lparam):
        u32, sh32 = ctypes.windll.user32, ctypes.windll.shell32
        if msg == WM_APP_TRAY:
            if lparam == WM_RBUTTONUP:
                self._menu()
            elif lparam == WM_LBUTTONDBLCLK:
                self._do(0)
            return 0
        if msg == self._taskbar_created:            # explorateur relancé : remettre l'icône
            sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid()))
            return 0
        if msg == WM_CLOSE:
            sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))
            u32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            u32.PostQuitMessage(0)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)
