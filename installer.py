#!/usr/bin/env python3
"""Installeur XTouch-LV1 (« XTouch_LV1_Install.exe », demande de Joseph du 16/10/2026 : un clic installe tout).

Compilé par build.py (PyInstaller onefile, le programme est embarqué dans l'exe). Fenêtre tkinter, textes en ANGLAIS.
Ce qu'il fait :
  1. copie le programme dans %LOCALAPPDATA%\\Programs\\XTouch-LV1 (réglages et journaux déjà là : jamais écrasés) ;
     s'il trouve des réglages (xtouch_courbe_fader.json…) À CÔTÉ de l'installeur, il les reprend s'ils manquent ;
  2. raccourcis Bureau + menu Démarrer (XTouch-LV1, Uninstall XTouch-LV1) ;
  3. Reaper (%APPDATA%\\REAPER, Reaper FERMÉ, sinon il réécrirait ses fichiers en quittant) :
     - déclare les scripts lv1_scenes / lv1_sync_tracks / lv1_meter_bridge dans reaper-kb.ini (les anciennes lignes
       lv1_*.lua, ex. vers le dossier de développement, sont remplacées) ;
     - Scripts\\__startup.lua : bloc marqué qui lance les scènes et la barre de vumètres au démarrage de Reaper ;
     - surface OSC 8000 -> 127.0.0.1:9000 ajoutée dans REAPER.ini si aucune surface OSC n'écoute sur 8000.
Désinstallation : « Uninstall XTouch-LV1 » (copie de cet exe dans le dossier du programme, option --uninstall).

Essai sans rien toucher au vrai système : py installer.py --source build/out/XTouch-LV1 --target DIR --reaper DIR
--no-shortcuts (voir tests/test_installer.py).
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading

NAME = "XTouch-LV1"
VERSION = "0.1"
EXE = NAME + ".exe"
PERSONAL = ["xtouch_courbe_fader.json", "xtouch_ecran.json", "xtouch_couleurs.json"]
SCRIPTS = ["lv1_scenes.lua", "lv1_sync_tracks.lua", "lv1_meter_bridge.lua"]        # actions déclarées
STARTUP = ["lv1_scenes.lua", "lv1_meter_bridge.lua"]                              # lancées avec Reaper
BEGIN, END = "-- XTouch-LV1 begin (installer, do not edit)", "-- XTouch-LV1 end"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def default_target():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", NAME)


def default_reaper():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "REAPER")


def bundled_source():
    """Programme embarqué (exe compilé) ; sinon la compilation locale de build.py."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "app")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "out", NAME)


def running(image):
    """True si un processus de ce nom tourne (tasklist)."""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % image, "/NH"], capture_output=True,
                             text=True, creationflags=NO_WINDOW).stdout
    except OSError:
        return False
    return image.lower() in out.lower()


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        lines = f.read().replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def write_lines(path, lines):
    while lines and lines[-1] == "":
        lines.pop()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")


# ---------------------------------------------------------------- programme

def copy_app(src, target, log):
    os.makedirs(target, exist_ok=True)
    shutil.rmtree(os.path.join(target, "_internal"), ignore_errors=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(target, name)
        if name in PERSONAL and os.path.exists(d):
            continue                                       # réglage de l'utilisateur : on le garde
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    log("Program installed in %s" % target)
    if getattr(sys, "frozen", False):                      # même exe = désinstalleur
        shutil.copy2(sys.executable, os.path.join(target, "Uninstall %s.exe" % NAME))
    if not getattr(sys, "frozen", False):
        return
    here = os.path.dirname(sys.executable)
    for f in PERSONAL:              # réglages posés à côté de l'installeur, ou dans dist/XTouch-LV1 (compilation de Joseph)
        for s in (os.path.join(here, f), os.path.join(here, NAME, f)):
            d = os.path.join(target, f)
            if os.path.exists(s) and not os.path.exists(d):
                shutil.copy2(s, d)
                log("Settings imported: %s" % f)


def shortcuts(target, log, remove=False):
    if sys.platform != "win32":
        return
    menu = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", NAME)
    ps = ("$d=[Environment]::GetFolderPath('Desktop');" "$p=Join-Path $d '%s.lnk';" % NAME)
    if remove:
        ps += "Remove-Item -LiteralPath $p -ErrorAction SilentlyContinue"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW)
        shutil.rmtree(menu, ignore_errors=True)
        log("Shortcuts removed")
        return
    os.makedirs(menu, exist_ok=True)
    links = [("$p", EXE), ("'%s'" % os.path.join(menu, NAME + ".lnk"), EXE),
             ("'%s'" % os.path.join(menu, "Uninstall %s.lnk" % NAME), "Uninstall %s.exe" % NAME)]
    for lnk, exe in links:
        if not os.path.exists(os.path.join(target, exe)):
            continue
        ps += ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);$s.TargetPath='%s';"
               "$s.WorkingDirectory='%s';$s.Save();" % (lnk, os.path.join(target, exe), target))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW)
    log("Shortcuts created (Desktop, Start menu)")


# ---------------------------------------------------------------- Reaper

def command_id(path):
    return "RS" + hashlib.sha1(path.lower().encode("utf-8")).hexdigest()


def reaper_actions(reaper, target, log, remove=False):
    kb = os.path.join(reaper, "reaper-kb.ini")
    lines = [l for l in read_lines(kb) if not re.search(r'"Custom: lv1_[a-z_]+\.lua"', l)]
    ids = {}
    if not remove:
        for s in SCRIPTS:
            path = os.path.join(target, "reaper", s)
            ids[s] = command_id(path)
            lines.append('SCR 4 0 %s "Custom: %s" %s' % (ids[s], s, ('"%s"' % path) if " " in path else path))
    write_lines(kb, lines)
    log("REAPER actions %s" % ("removed" if remove else "registered: " + ", ".join(SCRIPTS)))
    return ids


def reaper_startup(reaper, ids, log, remove=False):
    path = os.path.join(reaper, "Scripts", "__startup.lua")
    lines, skip = [], False
    for l in read_lines(path):                             # on retire notre ancien bloc, on garde le reste
        if l == BEGIN:
            skip = True
        elif l == END and skip:
            skip = False
        elif not skip:
            lines.append(l)
    if not remove:
        lines += [BEGIN]
        for s in STARTUP:
            lines.append('do local c = reaper.NamedCommandLookup("_%s") if c ~= 0 then reaper.Main_OnCommand(c, 0) end'
                         ' end  -- %s' % (ids[s], s))
        lines += [END]
    if any(l.strip() for l in lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_lines(path, lines)
    elif os.path.exists(path):
        os.remove(path)
    log("REAPER startup: %s" % ("removed" if remove else "scenes link + meter bridge start with REAPER"))


def reaper_osc(reaper, log):
    ini = os.path.join(reaper, "REAPER.ini")
    lines = read_lines(ini)
    if not lines:
        log("REAPER.ini not found: OSC not configured")
        return
    surf = [l for l in lines if re.match(r"csurf_\d+=", l)]
    if any(l.split("=", 1)[1].startswith("OSC ") and " 8000 " in l for l in surf):
        log("REAPER OSC (port 8000): already configured")
        return
    n = 0
    for i, l in enumerate(lines):
        if l.startswith("csurf_cnt="):
            n = int(l.split("=", 1)[1] or 0)
            lines[i] = "csurf_cnt=%d" % (n + 1)
            break
    else:
        sec = lines.index("[reaper]") if "[reaper]" in lines else -1
        if sec < 0:
            lines[:0] = ["[reaper]"]
            sec = 0
        lines.insert(sec + 1, "csurf_cnt=1")
    at = max(i for i, l in enumerate(lines) if l.startswith("csurf_cnt="))
    lines.insert(at + 1, 'csurf_%d=OSC "XTouch-LV1" 3 8000 "127.0.0.1" 9000 1024 10 ""' % n)
    write_lines(ini, lines)
    log("REAPER OSC surface added (receive 8000, send 127.0.0.1:9000)")


# ---------------------------------------------------------------- étapes

def install(src, target, reaper, log, do_shortcuts=True):
    if not os.path.exists(os.path.join(src, EXE)):
        raise RuntimeError("program files not found (%s)" % src)
    copy_app(src, target, log)
    if do_shortcuts:
        shortcuts(target, log)
    if os.path.isdir(reaper):
        ids = reaper_actions(reaper, target, log)
        reaper_startup(reaper, ids, log)
        reaper_osc(reaper, log)
    else:
        log("REAPER not found (%s): skipped" % reaper)
    log("Done. Start %s from the Desktop shortcut." % NAME)


def uninstall(target, reaper, log, keep_settings, do_shortcuts=True):
    if do_shortcuts:
        shortcuts(target, log, remove=True)
    if os.path.isdir(reaper):
        reaper_actions(reaper, target, log, remove=True)
        reaper_startup(reaper, {}, log, remove=True)       # la surface OSC reste (elle peut servir à autre chose)
    if keep_settings:
        for name in os.listdir(target) if os.path.isdir(target) else []:
            if name not in PERSONAL and not name.startswith("xtouch_journal_") and not name.startswith("Uninstall"):
                p = os.path.join(target, name)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        log("Program removed, settings kept in %s" % target)
    else:
        log("Program removed")
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        # l'exe en cours ne peut pas s'effacer lui-même : cmd s'en charge 3 s après
        what = ('del /f /q "%s"' % sys.executable) if keep_settings else ('rmdir /s /q "%s"' % target)
        subprocess.Popen('cmd /c ping -n 4 127.0.0.1 >nul & %s' % what, creationflags=NO_WINDOW, shell=True)
    elif not keep_settings:
        shutil.rmtree(target, ignore_errors=True)


# ---------------------------------------------------------------- fenêtre

def gui(a):
    import tkinter as tk
    from tkinter import messagebox
    removing = a.uninstall
    root = tk.Tk()
    root.title("%s %s v%s" % (NAME, "Uninstall" if removing else "Setup", VERSION))
    root.configure(bg="#111213")
    root.geometry("620x380")
    tk.Label(root, text=NAME + "  v" + VERSION, fg="#e9edf0", bg="#111213",
             font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
    tk.Label(root, text=("Removes the program, its shortcuts and its REAPER actions." if removing else
                         "X-Touch + Extender for Waves eMotion LV1, with REAPER integration."),
             fg="#9aa0a6", bg="#111213", font=("Segoe UI", 10)).pack(anchor="w", padx=16)
    box = tk.Text(root, height=12, bg="#1b1d20", fg="#e9edf0", relief="flat", font=("Consolas", 9))
    box.pack(fill="both", expand=True, padx=16, pady=10)
    bar = tk.Frame(root, bg="#111213")
    bar.pack(fill="x", padx=16, pady=(0, 14))

    def log(msg):
        root.after(0, lambda: (box.insert("end", msg + "\n"), box.see("end")))

    def blocked():
        for image, label in (("reaper.exe", "REAPER"), (EXE, NAME)):
            if running(image):
                return label
        return None

    def work():
        try:
            if removing:
                keep = messagebox.askyesno(NAME, "Keep your settings (fader calibration, screen layout)?")
                uninstall(a.target, a.reaper, log, keep, not a.no_shortcuts)
            else:
                install(a.source, a.target, a.reaper, log, not a.no_shortcuts)
        except Exception as e:                             # message lisible plutôt qu'une fenêtre qui disparaît
            log("ERROR: %s" % e)
        root.after(0, lambda: (go.config(state="normal", text="Close", command=root.destroy)))

    def start():
        who = blocked()
        if who:
            messagebox.showwarning(NAME, "Please close %s first, then click %s again." %
                                   (who, "Uninstall" if removing else "Install"))
            return
        go.config(state="disabled")
        threading.Thread(target=work, daemon=True).start()

    go = tk.Button(bar, text="Uninstall" if removing else "Install", command=start, bg="#38c9ff", fg="#111213",
                   relief="flat", font=("Segoe UI", 11, "bold"), padx=24, pady=6)
    go.pack(side="right")
    log(("Folder: %s" % a.target))
    if not removing:
        log("REAPER settings: %s" % a.reaper)
        log("Close REAPER and %s before installing." % NAME)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Installeur XTouch-LV1")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--source", default=bundled_source())
    ap.add_argument("--target", default=None)
    ap.add_argument("--reaper", default=default_reaper())
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--silencieux", action="store_true", help="sans fenêtre (tests)")
    ap.add_argument("--garder-reglages", action="store_true", help="désinstallation silencieuse : garder les réglages")
    a = ap.parse_args()
    if a.target is None:                                   # désinstalleur = dans le dossier du programme
        a.target = (os.path.dirname(sys.executable) if a.uninstall and getattr(sys, "frozen", False)
                    else default_target())
    if os.path.basename(sys.executable).lower().startswith("uninstall"):
        a.uninstall = True
        a.target = os.path.dirname(sys.executable)
    if a.silencieux:
        if a.uninstall:
            uninstall(a.target, a.reaper, print, a.garder_reglages, not a.no_shortcuts)
        else:
            install(a.source, a.target, a.reaper, print, not a.no_shortcuts)
        return 0
    gui(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
