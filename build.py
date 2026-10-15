#!/usr/bin/env python3
"""Compilation de XTouch-LV1 : produit l'installeur « dist/XTouch_LV1_Install.exe » (un double-clic installe tout).

    py build.py

1. PyInstaller compile le pont (xtouch_lv1_display.py, overlay Qt compris : « XTouch-LV1.exe --overlay ») en dossier
   (onedir, console, droits administrateur demandés au lancement) ;
2. le dossier est complété (reaper/*.lua, LISEZMOI.md, xtouch_couleurs.exemple.json) dans build/stage/XTouch-LV1 ;
3. PyInstaller compile installer.py en UN fichier qui embarque ce dossier.
Ce que fait l'installeur : voir installer.py. Rien de personnel (calibration, réglage d'écran, journaux) n'est
embarqué ; l'installeur reprend les réglages posés à côté de lui (ou dans dist/XTouch-LV1, ancienne compilation).
Il faut PyInstaller (py -m pip install pyinstaller) et PySide6.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "XTouch-LV1"
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "build")
SHARED = ["LISEZMOI.md", "xtouch_couleurs.exemple.json"]


def version():
    with open(os.path.join(HERE, "xtouch_lv1_display.py"), encoding="utf-8") as f:
        return re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)


def pyinstaller(args):
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--workpath", os.path.join(WORK, "work"), "--specpath", WORK] + args, cwd=HERE)
    if r.returncode:
        raise SystemExit("ÉCHEC de PyInstaller (code %d)." % r.returncode)


def main():
    ver = version()
    with open(os.path.join(HERE, "installer.py"), encoding="utf-8") as f:
        if 'VERSION = "%s"' % ver not in f.read():
            print("installer.py : VERSION différente de xtouch_lv1_display.py (%s)" % ver)
            return 1
    print("Compilation de %s v%s..." % (NAME, ver))
    out = os.path.join(WORK, "out")
    pyinstaller(["--console", "--uac-admin", "--name", NAME, "--distpath", out,
                 "--hidden-import", "xtouch_overlay_qt", os.path.join(HERE, "xtouch_lv1_display.py")])

    stage = os.path.join(WORK, "stage", NAME)
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(os.path.join(out, NAME), stage)
    os.makedirs(os.path.join(stage, "reaper"))
    for f in os.listdir(os.path.join(HERE, "reaper")):
        if f.endswith(".lua"):
            shutil.copy2(os.path.join(HERE, "reaper", f), os.path.join(stage, "reaper", f))
    for f in SHARED:
        shutil.copy2(os.path.join(HERE, f), os.path.join(stage, f))

    pyinstaller(["--onefile", "--windowed", "--name", "XTouch_LV1_Install", "--distpath", DIST,
                 "--add-data", "%s%sapp" % (stage, os.pathsep), os.path.join(HERE, "installer.py")])
    exe = os.path.join(DIST, "XTouch_LV1_Install.exe")
    print("OK : %s (%.0f Mo)" % (exe, os.path.getsize(exe) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
