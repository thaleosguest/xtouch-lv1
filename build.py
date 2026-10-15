#!/usr/bin/env python3
"""Compilation de XTouch-LV1 (V0.1, « plug and play ») : un seul exe qui contient le pont ET l'overlay Qt.

    py build.py

Résultat :
  dist/XTouch-LV1/            dossier à utiliser (double-clic sur XTouch-LV1.exe, demande les droits administrateur)
      XTouch-LV1.exe, _internal/      le programme (remplacés à chaque compilation)
      reaper/*.lua                    scripts Reaper (Load ReaScript… depuis ce dossier)
      xtouch_courbe_fader.json, xtouch_ecran.json, xtouch_couleurs.json
                                      réglages de Joseph : copiés UNE SEULE FOIS, jamais écrasés ensuite
      xtouch_journal_*.txt            journaux écrits par l'exe
  dist/XTouch-LV1-v0.1.zip    version à donner (sans réglages personnels ni journaux)

L'exe sans argument = « --clic-lv1 --attendre » (attend le branchement des X-Touch). Avec des arguments, ce sont les
mêmes options que xtouch_lv1_display.py. « XTouch-LV1.exe --overlay --reglage » = réglage du rappel de pistes.
Il faut PyInstaller (py -m pip install pyinstaller) et PySide6.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "XTouch-LV1"
DIST = os.path.join(HERE, "dist")
APP = os.path.join(DIST, NAME)
WORK = os.path.join(HERE, "build")
PERSONAL = ["xtouch_courbe_fader.json", "xtouch_ecran.json", "xtouch_couleurs.json"]   # jamais écrasés
SHARED = ["LISEZMOI.md", "xtouch_couleurs.exemple.json"]                                 # remplacés


def version():
    with open(os.path.join(HERE, "xtouch_lv1_display.py"), encoding="utf-8") as f:
        return re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)


def main():
    ver = version()
    tmp = os.path.join(WORK, "out")
    print("Compilation de %s v%s..." % (NAME, ver))
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--console", "--uac-admin",
           "--name", NAME, "--distpath", tmp, "--workpath", os.path.join(WORK, "work"),
           "--specpath", WORK, "--hidden-import", "xtouch_overlay_qt",
           os.path.join(HERE, "xtouch_lv1_display.py")]
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode:
        print("ÉCHEC de PyInstaller (code %d)." % r.returncode)
        return r.returncode
    built = os.path.join(tmp, NAME)

    # Le dossier final garde les réglages et journaux : on n'y remplace que le programme.
    os.makedirs(APP, exist_ok=True)
    shutil.rmtree(os.path.join(APP, "_internal"), ignore_errors=True)
    shutil.copytree(os.path.join(built, "_internal"), os.path.join(APP, "_internal"))
    shutil.copy2(os.path.join(built, NAME + ".exe"), os.path.join(APP, NAME + ".exe"))
    os.makedirs(os.path.join(APP, "reaper"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "reaper")):
        if f.endswith(".lua"):
            shutil.copy2(os.path.join(HERE, "reaper", f), os.path.join(APP, "reaper", f))
    for f in SHARED:
        shutil.copy2(os.path.join(HERE, f), os.path.join(APP, f))
    for f in PERSONAL:
        src, dst = os.path.join(HERE, f), os.path.join(APP, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print("  réglage copié : %s" % f)

    # Zip à donner : programme + scripts + mode d'emploi, sans réglages personnels ni journaux.
    zpath = os.path.join(DIST, "%s-v%s.zip" % (NAME, ver))
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(built):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.join(NAME, os.path.relpath(p, built)))
        for f in os.listdir(os.path.join(HERE, "reaper")):
            if f.endswith(".lua"):
                z.write(os.path.join(HERE, "reaper", f), os.path.join(NAME, "reaper", f))
        for f in SHARED:
            z.write(os.path.join(HERE, f), os.path.join(NAME, f))
    print("OK : %s\n     %s (%.0f Mo)" % (os.path.join(APP, NAME + ".exe"), zpath, os.path.getsize(zpath) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
