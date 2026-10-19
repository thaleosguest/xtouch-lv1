"""MIDI de Windows (winmm) : entrées en file d'attente, sorties qui survivent au débranchement de la X-Touch.

Déplacé tel quel de `xtouch_lv1_display.py` (étape 6 du refactor, 19/10/2026), qui le réexporte. Les sorties
elles-mêmes (`midiOutOpen`…) sont dans `xtouch_probe.WinMidi`.
"""
import time


class WinMidiIn:
    """Entrée MIDI Windows (winmm). Les messages arrivent dans une file : (unité, status, d1, d2, instant)."""
    MIM_DATA = 0x3C3
    CALLBACK_FUNCTION = 0x00030000

    def __init__(self, events):
        import ctypes
        from ctypes import wintypes as wt
        self.ct = ctypes
        self.w = ctypes.WinDLL("winmm")
        self.events = events
        self.handles = []
        self._keep = []

        class MIDIINCAPSW(ctypes.Structure):
            _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                        ("szPname", wt.WCHAR * 32), ("dwSupport", wt.DWORD)]
        self.CAPS = MIDIINCAPSW
        self.PROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, wt.UINT, ctypes.c_size_t,
                                       ctypes.c_size_t, ctypes.c_size_t)
        w = self.w
        w.midiInGetNumDevs.restype = wt.UINT
        w.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIINCAPSW), wt.UINT]
        w.midiInOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), wt.UINT, ctypes.c_void_p,
                                 ctypes.c_size_t, wt.DWORD]
        w.midiInStart.argtypes = [ctypes.c_void_p]
        w.midiInStop.argtypes = [ctypes.c_void_p]
        w.midiInClose.argtypes = [ctypes.c_void_p]

    def list(self):
        out = []
        for i in range(self.w.midiInGetNumDevs()):
            caps = self.CAPS()
            if self.w.midiInGetDevCapsW(i, self.ct.byref(caps), self.ct.sizeof(caps)) == 0:
                out.append((i, caps.szPname))
        return out

    def open(self, index, unit):
        def cb(hmi, msg, inst, p1, p2, unit=unit):
            if msg == self.MIM_DATA:
                self.events.put((unit, p1 & 0xFF, (p1 >> 8) & 0x7F, (p1 >> 16) & 0x7F, time.time()))
        proc = self.PROC(cb)
        self._keep.append(proc)
        h = self.ct.c_void_p()
        r = self.w.midiInOpen(self.ct.byref(h), index, self.ct.cast(proc, self.ct.c_void_p), 0,
                              self.CALLBACK_FUNCTION)
        if r != 0:
            raise OSError("entrée MIDI %d : erreur %d%s" % (index, r, " (déjà ouverte ?)" if r == 4 else ""))
        self.w.midiInStart(h)
        self.handles.append(h)
        return h

    def close_all(self):
        for h in self.handles:
            try:
                self.w.midiInStop(h)
                self.w.midiInClose(h)
            except OSError:
                pass
        self.handles = []


class SafeMidi:
    """Sorties MIDI qui ne plantent pas quand la X-Touch disparaît (USB débranché, veille, X-Touch éteinte : « envoi
    court : There is no driver installed on your system », plantage de la 0.2 chez Joseph le 18/10). La 1re erreur est
    notée dans `lost`, les envois suivants sont ignorés, et la boucle principale attend la X-Touch puis rouvre tout."""

    def __init__(self, midi):
        self.midi, self.lost = midi, None

    def list(self):
        return self.midi.list()

    def open(self, index):
        return self.midi.open(index)

    def close(self, h):
        try:
            self.midi.close(h)
        except OSError:
            pass

    def short(self, h, *args):
        if self.lost:
            return
        try:
            self.midi.short(h, *args)
        except OSError as e:
            self.lost = str(e)

    def long(self, h, data):
        if self.lost:
            return
        try:
            self.midi.long(h, data)
        except OSError as e:
            self.lost = str(e)
