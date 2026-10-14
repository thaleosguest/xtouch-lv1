#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test X-Touch / X-Touch Extender en USB : texte, couleurs des scribble strips, vumètres.

Envoie des messages au format Mackie Control et note tes réponses (o/n) dans un rapport.
Windows uniquement (API MIDI winmm par ctypes) ; Python 3 standard, rien à installer.

Messages utilisés (à valider par CE test, pas encore vérifiés sur ton matériel) :
  - en-tête SysEx Mackie : F0 00 00 66 <id>, id 0x14 = X-Touch, 0x15 = Extender
    (source : forum Ardour, « X-Touch scribble strips? », message de juillet 2022)
  - couleurs   : <en-tête> 72 c1..c8 F7, c = 0 vide, 1 rouge, 2 vert, 3 jaune, 4 bleu, 5 violet, 6 cyan, 7 blanc
  - texte LCD  : <en-tête> 12 <position> <texte ASCII> F7 (7 caractères par tranche, ligne 2 à partir de 56)
  - vumètres   : channel pressure D0, valeur = tranche*16 + niveau (niveau 0..12 supposé)
  - mode vumètre : <en-tête> 20 <tranche> <mode> F7 (facultatif)

AVANT : la X-Touch doit être en mode Mackie Control (MC) ; et la LV1 ne doit pas avoir ouvert
ses ports MIDI (dans System Inventory, retire le contrôleur Mackie ou ferme la LV1 pendant ce test).

Usage :
    py xtouch_probe.py --list           # liste les ports MIDI
    py xtouch_probe.py                  # choisit X-Touch et Extender tout seul
    py xtouch_probe.py --main 2 --ext 3 # ports donnés par numéro
    py xtouch_probe.py --dry-run        # affiche les octets sans rien envoyer
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

ID_MAIN = 0x14
ID_EXT = 0x15
COLOR_NAMES = ["vide", "rouge", "vert", "jaune", "bleu", "violet", "cyan", "blanc"]


# ─── Construction des messages (indépendant de Windows) ───────────────────────

def sysex(dev, body):
    return bytes([0xF0, 0x00, 0x00, 0x66, dev] + list(body) + [0xF7])


def msg_colors(dev, colors):
    colors = list(colors)[:8] + [7] * (8 - len(list(colors)[:8]))
    return sysex(dev, [0x72] + [c & 0x07 for c in colors])


def msg_lcd(dev, offset, text):
    data = [min(0x7E, max(0x20, ord(ch))) if ord(ch) < 128 else 0x3F for ch in text]
    return sysex(dev, [0x12, offset & 0x7F] + data)


def msg_lcd_strips(dev, row, labels):
    """row 0 = haut, 1 = bas ; 8 étiquettes de 7 caractères max."""
    text = "".join(lbl[:7].ljust(7) for lbl in (list(labels) + [""] * 8)[:8])
    return msg_lcd(dev, 0 if row == 0 else 56, text)


def msg_meter_mode(dev, strip, mode):
    return sysex(dev, [0x20, strip & 0x07, mode & 0x7F])


def msg_meter(strip, level):
    """Message court (status, data1). level 0..12 (14 et 15 = surcharge marche/arrêt selon la norme MCU)."""
    return (0xD0, ((strip & 0x07) << 4) | (level & 0x0F))


def hexs(b):
    return " ".join("%02X" % x for x in b)


# ─── Sortie MIDI Windows (winmm) ──────────────────────────────────────────────

class WinMidiOut:
    MHDR_DONE = 0x00000001

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt
        self.ct = ctypes
        self.wt = wt
        self.winmm = ctypes.WinDLL("winmm")

        class MIDIOUTCAPSW(ctypes.Structure):
            _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                        ("szPname", wt.WCHAR * 32), ("wTechnology", wt.WORD), ("wVoices", wt.WORD),
                        ("wNotes", wt.WORD), ("wChannelMask", wt.WORD), ("dwSupport", wt.DWORD)]

        class MIDIHDR(ctypes.Structure):
            pass
        MIDIHDR._fields_ = [("lpData", ctypes.c_char_p), ("dwBufferLength", wt.DWORD),
                            ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_size_t),
                            ("dwFlags", wt.DWORD), ("lpNext", ctypes.POINTER(MIDIHDR)),
                            ("reserved", ctypes.c_size_t), ("dwOffset", wt.DWORD),
                            ("dwReserved", ctypes.c_size_t * 8)]
        self.CAPS = MIDIOUTCAPSW
        self.HDR = MIDIHDR
        w = self.winmm
        w.midiOutGetNumDevs.restype = wt.UINT
        w.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIOUTCAPSW), wt.UINT]
        w.midiOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), wt.UINT, ctypes.c_size_t,
                                  ctypes.c_size_t, wt.DWORD]
        w.midiOutShortMsg.argtypes = [ctypes.c_void_p, wt.DWORD]
        w.midiOutPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wt.UINT]
        w.midiOutUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wt.UINT]
        w.midiOutLongMsg.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wt.UINT]
        w.midiOutClose.argtypes = [ctypes.c_void_p]
        w.midiOutGetErrorTextW.argtypes = [wt.UINT, wt.LPWSTR, wt.UINT]

    def error_text(self, code):
        buf = self.ct.create_unicode_buffer(256)
        self.winmm.midiOutGetErrorTextW(code, buf, 256)
        return buf.value or ("erreur %d" % code)

    def list(self):
        out = []
        for i in range(self.winmm.midiOutGetNumDevs()):
            caps = self.CAPS()
            if self.winmm.midiOutGetDevCapsW(i, self.ct.byref(caps), self.ct.sizeof(caps)) == 0:
                out.append((i, caps.szPname))
        return out

    def open(self, index):
        h = self.ct.c_void_p()
        r = self.winmm.midiOutOpen(self.ct.byref(h), index, 0, 0, 0)
        if r != 0:
            hint = ""
            if r == 4:  # MMSYSERR_ALLOCATED
                hint = " (port déjà ouvert par une autre appli : la LV1 ?)"
            raise OSError("ouverture du port %d impossible : %s%s" % (index, self.error_text(r), hint))
        return h

    def short(self, h, status, d1, d2=0):
        r = self.winmm.midiOutShortMsg(h, status | (d1 << 8) | (d2 << 16))
        if r != 0:
            raise OSError("envoi court : " + self.error_text(r))

    def long(self, h, data):
        buf = self.ct.create_string_buffer(bytes(data), len(data))
        hdr = self.HDR()
        hdr.lpData = self.ct.cast(buf, self.ct.c_char_p)
        hdr.dwBufferLength = len(data)
        hdr.dwFlags = 0
        size = self.ct.sizeof(hdr)
        r = self.winmm.midiOutPrepareHeader(h, self.ct.byref(hdr), size)
        if r != 0:
            raise OSError("préparation SysEx : " + self.error_text(r))
        r = self.winmm.midiOutLongMsg(h, self.ct.byref(hdr), size)
        if r != 0:
            self.winmm.midiOutUnprepareHeader(h, self.ct.byref(hdr), size)
            raise OSError("envoi SysEx : " + self.error_text(r))
        t_end = time.time() + 1.0
        while not (hdr.dwFlags & self.MHDR_DONE) and time.time() < t_end:
            time.sleep(0.001)
        self.winmm.midiOutUnprepareHeader(h, self.ct.byref(hdr), size)

    def close(self, h):
        self.winmm.midiOutClose(h)


class DryOut:
    """Affiche les octets au lieu de les envoyer."""
    def list(self):
        return [(0, "X-Touch (simulé)"), (1, "X-Touch-Ext (simulé)")]

    def open(self, index):
        return index

    def short(self, h, status, d1, d2=0):
        pass

    def long(self, h, data):
        print("    -> port %s : %s" % (h, hexs(data)))

    def close(self, h):
        pass


# ─── Déroulé du test ──────────────────────────────────────────────────────────

def ask(question, answers, key, auto):
    if auto:
        answers[key] = "non demandé (--yes)"
        return
    while True:
        r = input("  %s [o/n/?] : " % question).strip().lower()
        if r in ("o", "oui", "y", "n", "non", "?"):
            answers[key] = {"o": "oui", "oui": "oui", "y": "oui", "n": "non", "non": "non", "?": "pas sûr"}[r]
            note = input("    Détail (Entrée pour passer) : ").strip()
            if note:
                answers[key + "_detail"] = note
            return


def pick_ports(ports, main_idx, ext_idx):
    def find(pred):
        for i, name in ports:
            if pred(name.upper()):
                return i
        return None
    if main_idx is None:
        main_idx = find(lambda n: "X-TOUCH" in n.replace("XTOUCH", "X-TOUCH") and "EXT" not in n
                        and "MINI" not in n and "COMPACT" not in n)
    if ext_idx is None:
        ext_idx = find(lambda n: "X-TOUCH" in n.replace("XTOUCH", "X-TOUCH") and "EXT" in n)
    return main_idx, ext_idx


def main():
    ap = argparse.ArgumentParser(description="Test X-Touch / Extender : texte, couleurs, vumètres.")
    ap.add_argument("--list", action="store_true", help="liste les ports MIDI de sortie et quitte")
    ap.add_argument("--main", type=int, help="numéro du port de la X-Touch")
    ap.add_argument("--ext", type=int, help="numéro du port de l'Extender")
    ap.add_argument("--dry-run", action="store_true", help="n'envoie rien, affiche les octets")
    ap.add_argument("--yes", action="store_true", help="ne pose pas de questions (déroulé seul)")
    a = ap.parse_args()

    if a.dry_run:
        midi = DryOut()
    elif sys.platform != "win32":
        print("Ce test utilise l'API MIDI de Windows. Sur un autre système : --dry-run.")
        return 2
    else:
        midi = WinMidiOut()

    ports = midi.list()
    print("Ports MIDI de sortie :")
    for i, name in ports:
        print("  %d : %s" % (i, name))
    if a.list:
        return 0
    main_idx, ext_idx = pick_ports(ports, a.main, a.ext)
    if main_idx is None and ext_idx is None:
        print("\nX-Touch introuvable. Vérifie le câble USB, puis donne les numéros : --main N --ext N")
        return 2

    targets = []  # (nom, id sysex, handle)
    for label, idx, dev in (("X-Touch", main_idx, ID_MAIN), ("Extender", ext_idx, ID_EXT)):
        if idx is None:
            print("  %s : non trouvée, ignorée." % label)
            continue
        name = dict(ports).get(idx, "?")
        try:
            h = midi.open(idx)
        except OSError as e:
            print("  %s : %s" % (label, e))
            continue
        print("  %s : port %d « %s » ouvert" % (label, idx, name))
        targets.append((label, dev, h, idx, name))
    if not targets:
        return 3

    answers = {}
    tested = [t[0] for t in targets]

    def each(fn):
        for label, dev, h, _, _ in targets:
            fn(label, dev, h)

    try:
        # 1. Texte
        print("\n[1/4] Texte sur les écrans")
        each(lambda lbl, dev, h: (midi.long(h, msg_lcd_strips(dev, 0, ["TEST %d" % (i + 1) for i in range(8)])),
                                  midi.long(h, msg_lcd_strips(dev, 1, [lbl[:7]] * 8))))
        print("  Envoyé : « TEST 1 » à « TEST 8 » en haut, le nom de l'appareil en bas.")
        ask("Le texte s'affiche sur %s ?" % " et ".join(tested), answers, "texte", a.yes)

        # 2. Couleurs fixes
        print("\n[2/4] Couleurs des scribble strips : une couleur par tranche")
        order = [0, 1, 2, 3, 4, 5, 6, 7]
        each(lambda lbl, dev, h: (midi.long(h, msg_lcd_strips(dev, 0, [COLOR_NAMES[c] for c in order])),
                                  midi.long(h, msg_colors(dev, order))))
        print("  De gauche à droite : vide, rouge, vert, jaune, bleu, violet, cyan, blanc.")
        ask("Les 8 tranches ont ces couleurs, dans cet ordre ?", answers, "couleurs_fixes", a.yes)

        # 3. Couleurs qui tournent
        print("\n[3/4] Couleurs qui changent toutes les 0,5 s pendant 5 s")
        t_end = time.time() + 5
        shift = 0
        while time.time() < t_end:
            cols = [((i + shift) % 7) + 1 for i in range(8)]
            each(lambda lbl, dev, h: midi.long(h, msg_colors(dev, cols)))
            shift += 1
            time.sleep(0.5)
        ask("Les couleurs ont changé en direct, sans clignoter ni rester bloquées ?", answers, "couleurs_dynamiques", a.yes)

        # 4. Vumètres
        print("\n[4/4] Vumètres : balayage pendant 8 s (10 rafraîchissements par seconde)")
        each(lambda lbl, dev, h: [midi.long(h, msg_meter_mode(dev, s, 0x03)) for s in range(8)])
        each(lambda lbl, dev, h: midi.long(h, msg_lcd_strips(dev, 0, ["VU %d" % (i + 1) for i in range(8)])))
        t0 = time.time()
        sent = 0
        while time.time() - t0 < 8:
            t = time.time() - t0
            for label, dev, h, _, _ in targets:
                for s in range(8):
                    lvl = int(round(6 + 6 * math.sin(2 * math.pi * (t * 0.5 + s / 8.0))))
                    st, d1 = msg_meter(s, max(0, min(12, lvl)))
                    midi.short(h, st, d1)
                    sent += 1
            time.sleep(0.1)
        print("  %d messages de vumètre envoyés." % sent)
        ask("Les vumètres des tranches ont bougé (vague de gauche à droite) ?", answers, "vumetres", a.yes)
    finally:
        # Remise à blanc
        for label, dev, h, _, _ in targets:
            try:
                for s in range(8):
                    st, d1 = msg_meter(s, 0)
                    midi.short(h, st, d1)
                midi.long(h, msg_colors(dev, [7] * 8))
                midi.long(h, msg_lcd_strips(dev, 0, [""] * 8))
                midi.long(h, msg_lcd_strips(dev, 1, [""] * 8))
            except OSError:
                pass
            midi.close(h)

    rep = {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "simulation": bool(a.dry_run),
        "ports": [{"appareil": lbl, "port": idx, "nom": name, "id_sysex": "0x%02X" % dev}
                  for lbl, dev, _, idx, name in targets],
        "reponses": answers,
    }
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xtouch_probe_report_%s.json" % stamp)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("\nRapport : %s\nEnvoie-moi ce fichier." % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
