#!/usr/bin/env python3
"""Indication à l'écran du PC du mode « sends on fader » (demande de Joseph, 15/10/2026).

Quand le mode change : un BANDEAU au centre de la LV1 (« SEND ON FADER : FX 1  Reverb ») pendant quelques
secondes, puis il disparaît et laisse un CADRE ROUGE autour de la fenêtre LV1 qui clignote très doucement, avec
le même texte en petit en bas au centre. Hors mode sends : rien.

Fenêtres tkinter (bibliothèque standard), toujours au-dessus, TRAVERSÉES PAR LES CLICS (WS_EX_TRANSPARENT) :
elles n'empêchent jamais un geste sur l'écran tactile de la LV1. Tout le tkinter vit dans son propre fil.

    py xtouch_overlay.py       # démo 12 s (bandeau puis cadre) sur la fenêtre LV1, ou sur l'écran entier
"""
import json
import math
import os
import sys
import threading
import time

BANNER_S = 2.5            # durée du bandeau après un changement
BLINK_S = 2.4             # période du clignotement doux du cadre
ALPHA_MIN, ALPHA_MAX = 0.35, 0.95
BORDER = 6                # épaisseur du cadre (px)
RED = "#E0262B"
KEY = "#FF00FE"           # couleur rendue transparente (intérieur du cadre)


def lv1_rect(mixer=1):
    """Zone client de la fenêtre LV1 (ou de son Mixer détaché), en coordonnées écran, ou None."""
    try:
        import lv1_clic
        t = lv1_clic.Target(mixer)
        return t.rect if t.hwnd and not lv1_clic.u32().IsIconic(t.hwnd) else None
    except Exception:
        return None


def click_through(widget):
    """Rend une fenêtre tk transparente aux clics (et hors de la barre des tâches, sans prise de focus)."""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        hwnd = int(widget.wm_frame(), 16)
        GWL_EXSTYLE = -20
        u32.GetWindowLongW.restype = ctypes.c_long
        style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000   # LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


class LV1Overlay(threading.Thread):
    def __init__(self, mixer=1, rect_fn=None):
        super().__init__(daemon=True)
        self.mixer = mixer
        self.rect_fn = rect_fn or (lambda: lv1_rect(self.mixer))
        self.lock = threading.Lock()
        self.text = None          # texte voulu (None = rien à l'écran)
        self.changed_at = 0.0
        self.stop_flag = False

    def set_info(self, text, sub=None, color=None):
        """Même interface que QtOverlay : « SEND ON FADER : FX 1  Reverb »."""
        if not text:
            self.set(None)
        elif text == "SELECT AN AUX":
            self.set("SEND ON FADER : SELECT AN AUX")
        else:
            self.set(send_text(text, sub))

    def stop(self):
        self.stop_flag = True

    def set_ab(self, ab, key):
        pass                      # pastille A/B : version Qt seulement

    def set_warn(self, text):
        pass                      # alerte « B PATCH » : version Qt seulement

    def set_recall(self, data):
        pass                      # rappel de pistes : version Qt seulement

    def set_layer(self, name, sub=None):
        pass                      # notification de couche : version Qt seulement

    def set_mixer(self, mixer):
        self.mixer = mixer        # Mixer suivi : fenêtre détachée « MIXER2 » le cas échéant (rect_fn lit self.mixer)

    def set(self, text):
        """Texte à afficher (None = mode normal). Un changement relance le bandeau."""
        with self.lock:
            if text != self.text:
                self.text = text
                self.changed_at = time.time()

    def run(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        frame = tk.Toplevel(root)
        frame.overrideredirect(True)
        frame.configure(bg=KEY)
        frame.attributes("-topmost", True)
        frame.attributes("-transparentcolor", KEY)
        canvas = tk.Canvas(frame, bg=KEY, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        banner = tk.Toplevel(root)
        banner.overrideredirect(True)
        banner.configure(bg=RED)
        banner.attributes("-topmost", True)
        # Indispensable : une fenêtre WS_EX_LAYERED (clics traversants) n'est dessinée qu'avec des attributs de
        # transparence (sinon invisible, vu le 15/10) ; -alpha les fixe.
        banner.attributes("-alpha", 0.95)
        label = tk.Label(banner, bg=RED, fg="white", font=("Segoe UI", 26, "bold"), padx=36, pady=18)
        label.pack()
        frame.withdraw()
        banner.withdraw()
        for w in (frame, banner):
            w.update_idletasks()
            click_through(w)
        st = {"rect": None, "rect_t": 0.0, "shown": None, "geom": None}

        def tick():
            if self.stop_flag:
                root.destroy()
                return
            now = time.time()
            with self.lock:
                text, since = self.text, self.changed_at
            if now - st["rect_t"] > 1.0:
                st["rect"], st["rect_t"] = self.rect_fn(), now
            rect = st["rect"]
            if not text or not rect:
                if st["shown"]:
                    frame.withdraw()
                    banner.withdraw()
                    st["shown"] = None
                root.after(100, tick)
                return
            x, y, w, h = rect
            if now - since < BANNER_S:
                if st["shown"] != ("banner", text):
                    frame.withdraw()
                    label.configure(text=text)
                    banner.deiconify()
                    banner.update_idletasks()
                    bw, bh = banner.winfo_reqwidth(), banner.winfo_reqheight()
                    banner.geometry("+%d+%d" % (x + (w - bw) // 2, y + (h - bh) // 2))
                    banner.lift()
                    st["shown"] = ("banner", text)
            else:
                geom = "%dx%d+%d+%d" % (w, h, x, y)
                if st["shown"] != ("frame", text) or st["geom"] != geom:
                    banner.withdraw()
                    frame.geometry(geom)
                    canvas.delete("all")
                    b = BORDER
                    canvas.create_rectangle(b // 2, b // 2, w - b // 2 - 1, h - b // 2 - 1, outline=RED, width=b)
                    tw = 11 * len(text) + 30
                    canvas.create_rectangle((w - tw) // 2, h - 30, (w + tw) // 2, h, fill=RED, outline=RED)
                    canvas.create_text(w // 2, h - 15, text=text, fill="white", font=("Segoe UI", 13, "bold"))
                    frame.deiconify()
                    frame.lift()
                    st["shown"], st["geom"] = ("frame", text), geom
                phase = 0.5 + 0.5 * math.sin(2 * math.pi * now / BLINK_S)
                frame.attributes("-alpha", ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * phase)
            root.after(60, tick)

        root.after(60, tick)
        root.mainloop()


class QtOverlay:
    """Version Qt (style X/M32 Gain Recall v3) : processus xtouch_overlay_qt.py piloté par stdin (JSON).
    Même interface que LV1Overlay : set_info(texte, sous-titre, couleur #rrggbb) ; None = mode normal."""

    def __init__(self, mixer=1):
        import subprocess
        here = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, "frozen", False):        # exe compilé (build.py) : le même exe joue l'overlay
            args = [sys.executable, "--overlay"]
        else:
            args = [sys.executable, os.path.join(here, "xtouch_overlay_qt.py")]
        args += ["--mixer=2"] if mixer == 2 else []
        flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, creationflags=flags)
        self.last = object()

    def set_info(self, text, sub=None, color=None):
        info = (text, sub, color) if text else None
        if info == self.last:
            return
        self.last = info
        msg = {"text": text, "sub": sub, "color": color} if text else {"text": None}
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def set_ab(self, ab, key):
        """Pastille A/B sur la User Key « FlipAB » (ab = "A", "B" ou None)."""
        info = (ab, key) if ab and key is not None else None
        if info == getattr(self, "last_ab", object()):
            return
        self.last_ab = info
        try:
            self.proc.stdin.write((json.dumps({"ab": ab if info else None, "key": key}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def set_warn(self, text):
        """Alerte dans la barre du haut de la LV1 (ex. « B PATCH » : diagonale B cassée) ; None = rien."""
        if text == getattr(self, "last_warn", object()):
            return
        self.last_warn = text
        try:
            self.proc.stdin.write((json.dumps({"warn": text}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def set_recall(self, data):
        """Rappel de pistes (bandeau aligné sur la surface) : dict, ou None pour le cacher."""
        try:
            self.proc.stdin.write((json.dumps({"recall": data}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def set_layer(self, name, sub=None):
        """Notification « LAYER  Ch 17-32 » en bas à droite de la LV1 (quelques secondes)."""
        try:
            self.proc.stdin.write((json.dumps({"layer": {"name": name, "sub": sub}}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def set_mixer(self, mixer):
        """Mixer suivi (1 / 2) : l'overlay se cale sur sa fenêtre (principale, ou « MIXER2 » détachée)."""
        try:
            self.proc.stdin.write((json.dumps({"mixer": mixer}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            pass

    def stop(self):
        try:
            self.proc.stdin.write(b'{"quit": true}\n')
            self.proc.stdin.close()
        except OSError:
            pass


def make_overlay(mixer=1):
    """Qt si PySide6 est installé (comme x32-gain-recall v3), sinon tkinter (bibliothèque standard)."""
    import importlib.util
    if importlib.util.find_spec("PySide6") is not None:
        try:
            return QtOverlay(mixer)
        except OSError:
            pass
    o = LV1Overlay(mixer)
    o.start()
    return o


def send_text(aux_name, track_name):
    """« SEND ON FADER : FX 1  Reverb » (nom de la piste ajouté s'il diffère du nom de l'aux)."""
    t = "SEND ON FADER : %s" % (aux_name or "?").upper()
    if track_name and track_name.strip() and track_name.strip().lower() != (aux_name or "").lower():
        t += "  %s" % track_name.strip()
    return t


if __name__ == "__main__":
    def full_screen():
        return lv1_rect() or (0, 0, 1280, 720)
    o = LV1Overlay(rect_fn=full_screen)
    o.start()
    o.set("SEND ON FADER : SELECT AN AUX")
    time.sleep(4)
    o.set(send_text("Fx 1", "Reverb"))
    time.sleep(8)
    o.stop_flag = True
    time.sleep(0.3)
