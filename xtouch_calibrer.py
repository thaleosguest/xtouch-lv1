#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibration des faders X-Touch : repères imprimés -> dB LV1.

Tu poses le fader 1 de la X-Touch sur un repère imprimé, tu tapes la valeur de ce repère
(10, 5, 0, -10…), Entrée ; on recommence pour chaque repère. Le script enregistre la courbe
dans xtouch_courbe_fader.json, lue au démarrage par xtouch_lv1_display.py (tous les faders,
master compris). Ensuite il pose le fader sur chaque repère avec le moteur, pour vérifier.

La LV1 n'est pas utilisée. Ferme xtouch_lv1_display.py avant (il tient les ports MIDI).
Windows uniquement. Python 3 standard.

Usage :
    py xtouch_calibrer.py
    py xtouch_calibrer.py --fader 9      # calibrer avec un autre fader (1-8 de la X-Touch, 9 = master)
"""
import argparse
import json
import os
import queue
import sys
import threading
import time

import xtouch_probe as X
import xtouch_lv1_display as D

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_mark(text):
    t = text.strip().lower().replace(",", ".").replace("db", "").replace("+", "").strip()
    if t in ("inf", "-inf", "bas", "min", "∞", "-∞"):
        return None          # bas de course : -inf, géré à part
    return float(t)


def main():
    ap = argparse.ArgumentParser(description="Calibration des faders X-Touch (repères imprimés -> dB).")
    ap.add_argument("--fader", type=int, default=1, help="fader utilisé : 1-8, ou 9 pour le master (1)")
    ap.add_argument("--main", type=int, help="port MIDI de sortie de la X-Touch")
    a = ap.parse_args()
    if sys.platform != "win32":
        print("Windows uniquement.")
        return 2
    chan = 8 if a.fader == 9 else a.fader - 1
    if not 0 <= chan <= 8:
        print("--fader doit valoir 1 à 9.")
        return 2

    out = X.WinMidiOut()
    o_main, _ = X.pick_ports(out.list(), a.main, None)
    if o_main is None:
        print("Sortie MIDI X-Touch introuvable (py xtouch_probe.py --list).")
        return 3
    h = out.open(o_main)
    events = queue.Queue()
    mi = D.WinMidiIn(events)
    i_main, _ = X.pick_ports(mi.list(), None, None)
    if i_main is None:
        print("Entrée MIDI X-Touch introuvable.")
        return 3
    mi.open(i_main, 0)

    def lcd(top, bottom=""):
        out.long(h, X.msg_lcd(X.ID_MAIN, 0, top[:56].ljust(56)))
        out.long(h, X.msg_lcd(X.ID_MAIN, 56, bottom[:56].ljust(56)))

    last = [None]
    running = [True]

    def pump():
        """Écho continu : chaque position reçue est renvoyée aussitôt à la X-Touch.
        Sans ça, au relâchement, la X-Touch ramène le fader à la dernière valeur reçue de l'ordinateur."""
        while running[0]:
            try:
                unit, st, d1, d2, t = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if st == 0xE0 | chan:
                last[0] = d1 | (d2 << 7)
                out.short(h, st, d1, d2)

    threading.Thread(target=pump, daemon=True).start()

    def drain():
        time.sleep(0.05)   # laisse passer les derniers messages

    marks = []   # (dB, valeur 14 bits)
    inf_mark = None
    print("Calibration avec le fader %s." % ("master" if chan == 8 else a.fader))
    print("Pour chaque repère imprimé : pose le fader dessus, tape la valeur du repère, Entrée.")
    print("Commence par le haut (+10), puis 5, 0, -5, -10, -20, -30, -40, -60… comme imprimé.")
    print("Pour le repère ∞ (moins l'infini), tape -inf.")
    print("Tape 'fin' quand c'est terminé (au moins 3 repères).\n")
    lcd("CALIBRATION : fader %s" % ("master" if chan == 8 else a.fader), "pose-le sur un repere puis tape sa valeur")
    try:
        while True:
            txt = input("  Repère (ou 'fin') : ")
            drain()
            if not txt.strip():
                continue
            if txt.strip().lower() in ("fin", "f", "q"):
                if len(marks) >= 3:
                    break
                print("    Il faut au moins 3 repères.")
                continue
            try:
                db = parse_mark(txt)
            except ValueError:
                print("    Valeur non comprise : tape un nombre (ex. -10) ou 'fin'.")
                continue
            if last[0] is None:
                print("    Aucune position reçue : bouge un peu le fader, repose-le sur le repère, recommence.")
                continue
            if db is None:
                inf_mark = last[0]
                print("    Repère -inf -> position %d (%.1f %% de la course)" % (last[0], 100.0 * last[0] / 16383))
                lcd("Repere -inf note", "position %d" % last[0])
                continue
            marks = [m for m in marks if m[0] != db] + [(db, last[0])]
            print("    %+.1f dB -> position %d (%.1f %% de la course)" % (db, last[0], 100.0 * last[0] / 16383))
            lcd("Repere %+.1f dB note" % db, "position %d" % last[0])
    except (KeyboardInterrupt, EOFError):
        print("\n  Arrêt.")

    marks.sort(key=lambda m: -m[0])
    bad = [(m1, m2) for m1, m2 in zip(marks, marks[1:]) if m2[1] >= m1[1]]
    if inf_mark is not None and marks and inf_mark >= marks[-1][1]:
        bad.append((marks[-1], ("-inf", inf_mark)))
    if len(marks) < 3 or bad:
        if bad:
            print("Courbe incohérente : un repère plus bas a une position plus haute :", bad)
        print("Rien n'est enregistré.")
        running[0] = False
        mi.close_all(); out.close(h)
        return 1
    curve = [[db, round(v / 16383.0, 4)] for db, v in marks]
    if inf_mark is not None:
        curve.append(["-inf", round(inf_mark / 16383.0, 4)])
    path = os.path.join(HERE, "xtouch_courbe_fader.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(curve, f, indent=1)
    print("\nCourbe enregistrée : %s" % path)
    for db, p in curve:
        print("  %8s dB  ->  %5.1f %%" % (db if isinstance(db, str) else "%+.1f" % db, 100 * p))

    # Vérification : le moteur pose le fader sur chaque repère.
    D.load_fader_curve()
    print("\nVérification : le moteur va poser le fader sur chaque repère (2 s chacun). Regarde s'il tombe pile.")
    running[0] = False   # plus d'écho : c'est le moteur qui pilote
    time.sleep(0.15)
    for db, _ in curve:
        if isinstance(db, str):
            continue
        v = D.db_to_fader(db)
        lcd("Verification", "%+.1f dB" % db)
        out.short(h, 0xE0 | chan, v & 0x7F, (v >> 7) & 0x7F)
        print("  %+.1f dB" % db)
        time.sleep(2)
    out.short(h, 0xE0 | chan, 0, 0)
    lcd("", "")
    mi.close_all()
    out.close(h)
    print("\nTerminé. Relance xtouch_lv1_display.py : il lit la nouvelle courbe au démarrage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
