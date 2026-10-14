#!/usr/bin/env python3
"""Décode les 12 entiers inconnus de /Channels à partir d'un journal xtouch_journal_*.txt.

Protocole de test (hors concert) : dans la LV1, muter In 1 et In 3, solo sur In 2, PUIS lancer
    py xtouch_lv1_display.py --lecture-seule --seconds 10
et passer le journal obtenu à ce script :
    py tests/analyser_channels.py xtouch_journal_XXXX.txt [--toutes]

Affiche, pour le premier /Channels du journal, les 19 champs des pistes d'entrée 1..6, puis les
colonnes dont la valeur sur In 1/In 3 (mute) ou In 2 (solo) diffère de la valeur majoritaire des
autres entrées : ce sont les candidates pour l'état mute/solo. Les /Notify/Track/Out/Mute et
/Notify/Solo du même journal sont rappelés pour confirmation.
"""
import ast
import re
import sys
from collections import Counter

TOKEN = re.compile(r"""([a-zA-Z]):('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\S+)""")
FIELDS = (["nom", "groupe", "canal", "d1(fader)", "d2"] + ["e%d" % k for k in range(1, 13)]
          + ["h", "d3"])


def parse_args(text):
    out = []
    for t, v in TOKEN.findall(text):
        if t == "b" or v.startswith("<"):
            out.append((t, None))
            continue
        try:
            out.append((t, ast.literal_eval(v)))
        except (ValueError, SyntaxError):
            out.append((t, v))
    return out


def read_journal(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(" ", 2)
            if len(parts) < 2 or not parts[1].startswith("/"):
                continue
            yield parts[1], parse_args(parts[2] if len(parts) > 2 else "")


def tracks_of(args):
    count = args[0][1] if args and args[0][0] == "i" else 0
    for k in range(count):
        base = 1 + k * 19
        if base + 19 > len(args):
            break
        yield [v for _, v in args[base:base + 19]]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, show_all = argv[1], "--toutes" in argv
    channels, notes = None, []
    for addr, args in read_journal(path):
        if addr == "/Channels" and channels is None:
            channels = list(tracks_of(args))
        elif addr in ("/Notify/Track/Out/Mute", "/Notify/Solo") and len(args) >= 3:
            if args[0][1] == 0 and args[1][1] < 6:
                notes.append("%s In %d -> %s" % (addr, args[1][1] + 1, args[2][1]))
    if not channels:
        print("Aucun /Channels dans ce journal.")
        return 1

    inputs = {t[2]: t for t in channels if t[1] == 0}
    print("%d pistes dans /Channels, dont %d entrées.\n" % (len(channels), len(inputs)))
    shown = [t for t in channels if show_all or (t[1] == 0 and t[2] < 6)]
    print(" | ".join("%-9s" % f for f in FIELDS))
    for t in shown:
        print(" | ".join("%-9s" % (("%.1f" % v) if isinstance(v, float) else v) for v in t))

    others = [t for c, t in inputs.items() if c not in (0, 1, 2)]
    if not others or not all(c in inputs for c in (0, 1, 2)):
        print("\nIn 1..3 ou les autres entrées manquent : comparaison impossible.")
        return 1
    print("\nColonnes candidates (valeur majoritaire des autres entrées -> In 1 / In 2 / In 3) :")
    found = False
    for i in range(5, 17):
        base = Counter(t[i] for t in others).most_common(1)[0][0]
        vals = [inputs[c][i] for c in (0, 1, 2)]
        if any(v != base for v in vals):
            found = True
            tag = ""
            if vals[0] != base and vals[2] != base and vals[1] == base:
                tag = "  <- mute probable"
            elif vals[1] != base and vals[0] == base and vals[2] == base:
                tag = "  <- solo probable"
            print("  %-4s : %s -> %s / %s / %s%s" % (FIELDS[i], base, vals[0], vals[1], vals[2], tag))
    if not found:
        print("  aucune : l'état mute/solo n'est pas dans les 12 entiers.")
    print("\nNotifications mute/solo vues dans le journal (In 1..6) :")
    for n in notes or ["  aucune"]:
        print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
