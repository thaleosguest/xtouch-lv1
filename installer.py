#!/usr/bin/env python3
"""Installeur « LV1 Suite » (demande de Joseph du 16/10/2026) : XTouch-LV1 et/ou X32 Gain Recall, au choix (cases à
cocher), un clic installe tout.

Compilé par build.py (PyInstaller onefile, les programmes sont embarqués dans l'exe). Fenêtre tkinter, textes en ANGLAIS.
Dossiers : %LOCALAPPDATA%\\Programs\\<appli>, et %LOCALAPPDATA%\\Programs\\LV1 Suite (désinstalleur = copie de cet exe,
installed.json = versions installées). Menu Démarrer : dossier « LV1 Suite » (applis, modes d'emploi, désinstalleur) ;
Bureau : un raccourci par appli.
XTouch-LV1 :
  - copie du programme (réglages et journaux déjà là : jamais écrasés ; réglages posés à côté de l'installeur, ou dans
    dist/XTouch-LV1, repris s'ils manquent) ;
  - Reaper (%APPDATA%\\REAPER, Reaper FERMÉ, sinon il réécrirait ses fichiers en quittant) : scripts lv1_scenes /
    lv1_sync_tracks / lv1_meter_bridge déclarés dans reaper-kb.ini (anciennes lignes lv1_*.lua remplacées) ;
    Scripts\\__startup.lua : bloc marqué qui lance les scènes et la barre de vumètres ; surface OSC 8000 -> 9000 ajoutée
    dans REAPER.ini si aucune surface OSC n'écoute sur 8000.
X32 Gain Recall : copie de l'exe (release GitHub, embarquée par build.py) + mode d'emploi ; ses données
(%APPDATA%\\X32 Gain Recall : scènes, réglages) ne sont JAMAIS touchées, même à la désinstallation. Sa case « lancer
avec Windows » (clé Run) est retirée à la désinstallation si elle visait l'exe installé.

Essai sans rien toucher au vrai système : tests/test_installer.py (dossiers temporaires), ou l'exe avec
--silencieux --no-shortcuts --root DIR --reaper DIR [--apps xtouch,gainrecall].
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading

SUITE = "LV1 Suite"
VERSION = "0.1"                                   # version de XTouch-LV1 (= xtouch_lv1_display.VERSION, build.py vérifie)
XT, RP, GR = "xtouch", "reaper", "gainrecall"
# RP (« REAPER LV1 », demande de Joseph) = intégration REAPER, sans dossier à elle : scripts dans <XTouch-LV1>\reaper,
# déclarés dans REAPER ; il lui faut XTouch-LV1 (le pont échange les scènes et les pistes avec les scripts).
APPS = {
    XT: {"name": "XTouch-LV1", "exe": "XTouch-LV1.exe", "manual": "MODE_EMPLOI.html",
         "about": "X-Touch + Extender for Waves eMotion LV1"},
    RP: {"name": "REAPER LV1", "exe": None, "manual": None,
         "about": "REAPER integration: LV1 scenes <-> markers, track sync, meter bridge (needs XTouch-LV1)"},
    GR: {"name": "X32 Gain Recall", "exe": "XM32_Gain_Recall_LV1.exe", "manual": "MODE_EMPLOI.html",
         "about": "X32 / M32 preamp gain recall for eMotion LV1"},
}
PERSONAL = ["xtouch_courbe_fader.json", "xtouch_ecran.json", "xtouch_couleurs.json"]
SCRIPTS = ["lv1_scenes.lua", "lv1_sync_tracks.lua", "lv1_meter_bridge.lua"]        # actions déclarées
STARTUP = ["lv1_scenes.lua", "lv1_meter_bridge.lua"]                              # lancées avec Reaper
BEGIN, END = "-- XTouch-LV1 begin (installer, do not edit)", "-- XTouch-LV1 end"
GR_RUN_KEY, GR_RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "X32 Gain Recall"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def default_root():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs")


def default_reaper():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "REAPER")


def app_dir(root, key):
    return os.path.join(root, APPS[XT if key == RP else key]["name"])


def suite_dir(root):
    return os.path.join(root, SUITE)


def bundled_sources():
    """{appli: dossier source} des programmes embarqués (exe compilé) ; sinon les compilations locales de build.py."""
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                           "build", "stage")
    out = {}
    for key in (XT, GR):
        d = os.path.join(base, key)
        if os.path.exists(os.path.join(d, APPS[key]["exe"])):
            out[key] = d
    if XT in out and os.path.isdir(os.path.join(out[XT], "reaper")):
        out[RP] = out[XT]                                  # scripts REAPER livrés avec XTouch-LV1
    return dict((k, out[k]) for k in APPS if k in out)    # dans l'ordre d'APPS (XTouch-LV1 avant REAPER LV1)


def source_version(key, src):
    if key in (XT, RP):
        return VERSION
    try:
        with open(os.path.join(src, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def installed(root):
    """{appli: version} des applis installées (présentes sur le disque)."""
    try:
        with open(os.path.join(suite_dir(root), "installed.json"), encoding="utf-8") as f:
            versions = json.load(f)
    except (OSError, ValueError):
        versions = {}
    have = {k: versions.get(k, "?") for k in (XT, GR) if os.path.exists(os.path.join(app_dir(root, k), APPS[k]["exe"]))}
    if XT in have and RP in versions:                      # REAPER LV1 : noté à l'installation
        have[RP] = versions[RP]
    return dict((k, have[k]) for k in APPS if k in have)


def save_installed(root, versions):
    os.makedirs(suite_dir(root), exist_ok=True)
    with open(os.path.join(suite_dir(root), "installed.json"), "w", encoding="utf-8") as f:
        json.dump(versions, f, indent=1)


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


# ---------------------------------------------------------------- programmes

def copy_xtouch(src, target, log):
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
    old = os.path.join(target, "Uninstall XTouch-LV1.exe")  # désinstalleur de la 1re version de l'installeur
    if os.path.exists(old):
        os.remove(old)
    log("XTouch-LV1 installed in %s" % target)
    if not getattr(sys, "frozen", False):
        return
    here = os.path.dirname(sys.executable)
    for f in PERSONAL:              # réglages posés à côté de l'installeur, ou dans dist/XTouch-LV1 (compilation de Joseph)
        for s in (os.path.join(here, f), os.path.join(here, "XTouch-LV1", f)):
            d = os.path.join(target, f)
            if os.path.exists(s) and not os.path.exists(d):
                shutil.copy2(s, d)
                log("Settings imported: %s" % f)


def copy_gainrecall(src, target, log):
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(target, name)
        if os.path.isdir(s):                               # assets/ (logo du mode d'emploi)
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    log("X32 Gain Recall installed in %s (scenes and settings stay in %%APPDATA%%\\X32 Gain Recall)" % target)


def gainrecall_autostart(target, log):
    """Désinstallation : retire la clé Run de Gain Recall si elle lance l'exe installé (pas une autre copie)."""
    if sys.platform != "win32":
        return
    import winreg
    exe = os.path.join(target, APPS[GR]["exe"]).lower()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GR_RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            cur = winreg.QueryValueEx(k, GR_RUN_NAME)[0]
            if exe in cur.lower():
                winreg.DeleteValue(k, GR_RUN_NAME)
                log("X32 Gain Recall: removed from Windows startup")
    except OSError:
        pass


def shortcuts(root, log):
    """Raccourcis selon ce qui est installé : dossier « LV1 Suite » du menu Démarrer refait, un raccourci Bureau par appli
    installée (retiré pour les autres)."""
    if sys.platform != "win32":
        return
    progs = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    menu = os.path.join(progs, SUITE)
    shutil.rmtree(menu, ignore_errors=True)
    shutil.rmtree(os.path.join(progs, "XTouch-LV1"), ignore_errors=True)     # ancien dossier (1re version)
    have = installed(root)
    uninst = os.path.join(suite_dir(root), "Uninstall %s.exe" % SUITE)
    ps = "$d=[Environment]::GetFolderPath('Desktop');$w=New-Object -ComObject WScript.Shell;"
    links = []
    for key, app in APPS.items():
        if not app["exe"]:                                 # REAPER LV1 : pas de programme à lancer
            continue
        desk = "(Join-Path $d '%s.lnk')" % app["name"]
        if key not in have:
            ps += "Remove-Item -LiteralPath %s -ErrorAction SilentlyContinue;" % desk
            continue
        d = app_dir(root, key)
        links += [(desk, os.path.join(d, app["exe"]), d),
                  ("'%s'" % os.path.join(menu, app["name"] + ".lnk"), os.path.join(d, app["exe"]), d),
                  ("'%s'" % os.path.join(menu, app["name"] + " Manual.lnk"), os.path.join(d, app["manual"]), d)]
    if have and os.path.exists(uninst):
        links.append(("'%s'" % os.path.join(menu, "Uninstall %s.lnk" % SUITE), uninst, suite_dir(root)))
    if have:
        os.makedirs(menu, exist_ok=True)
    for lnk, path, wd in links:
        if os.path.exists(path):
            ps += ("$s=$w.CreateShortcut(%s);$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save();"
                   % (lnk, path.replace("'", "''"), wd.replace("'", "''")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW)
    log("Shortcuts updated (Desktop, Start menu > %s)" % SUITE)


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

def install(sources, root, apps, reaper, log, do_shortcuts=True):
    """sources : {appli: dossier source} ; apps : applis cochées."""
    versions = installed(root)
    apps = [k for k in APPS if k in apps]                  # XTouch-LV1 avant REAPER LV1
    if RP in apps and XT not in apps and XT not in versions:
        raise RuntimeError("REAPER LV1 needs XTouch-LV1: tick it too")
    for key in apps:
        src = sources.get(key)
        if not src or not os.path.exists(os.path.join(src, APPS[XT if key == RP else key]["exe"])):
            raise RuntimeError("%s: program files not found" % APPS[key]["name"])
        target = app_dir(root, key)
        if key == XT:
            copy_xtouch(src, target, log)
        elif key == RP:
            if not os.path.isdir(reaper):
                log("REAPER LV1: REAPER settings not found (%s): skipped" % reaper)
                continue
            ids = reaper_actions(reaper, target, log)
            reaper_startup(reaper, ids, log)
            reaper_osc(reaper, log)
        else:
            copy_gainrecall(src, target, log)
        versions[key] = source_version(key, src)
    save_installed(root, versions)
    if getattr(sys, "frozen", False):                      # même exe = désinstalleur
        shutil.copy2(sys.executable, os.path.join(suite_dir(root), "Uninstall %s.exe" % SUITE))
    if do_shortcuts:
        shortcuts(root, log)
    log("Done. Start the programs from their Desktop shortcuts (manuals: Start menu > %s)." % SUITE)


def uninstall(root, apps, reaper, log, keep_settings, do_shortcuts=True):
    versions = installed(root)
    if XT in apps and RP not in apps and RP in versions:
        apps = list(apps) + [RP]                           # sans XTouch-LV1, les scripts REAPER n'existent plus
    apps = [k for k in APPS if k in apps]
    for key in apps:
        target = app_dir(root, key)
        if key == RP:
            if os.path.isdir(reaper):
                reaper_actions(reaper, target, log, remove=True)
                reaper_startup(reaper, {}, log, remove=True)   # la surface OSC reste (elle peut servir à autre chose)
        elif key == XT:
            if keep_settings:
                for name in os.listdir(target) if os.path.isdir(target) else []:
                    if name not in PERSONAL and not name.startswith("xtouch_journal_"):
                        p = os.path.join(target, name)
                        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
                log("XTouch-LV1 removed, settings kept in %s" % target)
            else:
                shutil.rmtree(target, ignore_errors=True)
                log("XTouch-LV1 removed")
        else:
            gainrecall_autostart(target, log)
            shutil.rmtree(target, ignore_errors=True)
            log("X32 Gain Recall removed (scenes and settings kept in %APPDATA%\\X32 Gain Recall)")
        versions.pop(key, None)
    left = installed(root)
    if do_shortcuts:
        shortcuts(root, log)
    if left:
        save_installed(root, {k: versions.get(k, v) for k, v in left.items()})
        return
    sd = suite_dir(root)                                   # plus rien d'installé : le dossier du désinstalleur part aussi
    if getattr(sys, "frozen", False) and sys.platform == "win32" and \
            os.path.dirname(sys.executable).lower() == sd.lower():
        # l'exe en cours ne peut pas s'effacer lui-même : cmd s'en charge 3 s après
        subprocess.Popen('cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "%s"' % sd, creationflags=NO_WINDOW, shell=True)
    else:
        shutil.rmtree(sd, ignore_errors=True)


# ---------------------------------------------------------------- fenêtre

def gui(a, sources):
    import tkinter as tk
    from tkinter import messagebox
    removing = a.uninstall
    have = installed(a.root)
    keys = [k for k in APPS if (k in have if removing else k in sources)]
    root = tk.Tk()
    root.title("%s %s" % (SUITE, "Uninstall" if removing else "Setup"))
    root.configure(bg="#111213")
    ico = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
    if os.path.exists(ico):                                # logo de XTouch-LV1 dans la barre de titre
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass
    root.geometry("720x600")
    bg, fg, dim = "#111213", "#e9edf0", "#9aa0a6"
    tk.Label(root, text=SUITE, fg=fg, bg=bg, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
    tk.Label(root, text="Choose what to %s:" % ("remove" if removing else "install"), fg=dim, bg=bg,
             font=("Segoe UI", 10)).pack(anchor="w", padx=16)
    picks = {}
    for k in keys:
        app = APPS[k]
        new = "v" + (have[k] if removing else source_version(k, sources[k]))
        cur = "" if removing else ("  (installed: v%s)" % have[k] if k in have else "")
        picks[k] = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="%s  %s%s\n%s" % (app["name"], new, cur, app["about"]), variable=picks[k],
                       justify="left", anchor="w", fg=fg, bg=bg, selectcolor="#1b1d20", activebackground=bg,
                       activeforeground=fg, font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(8, 0))
    if not keys:
        tk.Label(root, text="Nothing to %s." % ("remove" if removing else "install"), fg=fg, bg=bg,
                 font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=8)
    folder = tk.StringVar(value=a.root)
    if not removing:                                       # choix du dossier (demande de Joseph)
        row = tk.Frame(root, bg=bg)
        row.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(row, text="Install folder:", fg=dim, bg=bg, font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(row, textvariable=folder, bg="#1b1d20", fg=fg, insertbackground=fg, relief="flat",
                 font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, padx=8, ipady=3)

        def browse():
            from tkinter import filedialog
            d = filedialog.askdirectory(initialdir=folder.get(), title="Install folder")
            if d:
                folder.set(os.path.normpath(d))
        tk.Button(row, text="Browse…", command=browse, bg="#3a3e43", fg=fg, relief="flat",
                  font=("Segoe UI", 9)).pack(side="right")
    box = tk.Text(root, height=12, bg="#1b1d20", fg=fg, relief="flat", font=("Consolas", 9), wrap="word")
    box.pack(fill="both", expand=True, padx=16, pady=10)
    bar = tk.Frame(root, bg=bg)
    bar.pack(fill="x", padx=16, pady=(0, 14))
    started = [False]

    def log(msg):
        root.after(0, lambda: (box.insert("end", msg + "\n"), box.see("end")))

    def explain(*_):
        """Étapes de ce qui va être fait, selon les cases cochées et le dossier (avant de cliquer)."""
        if started[0]:
            return
        box.delete("1.0", "end")
        apps, r, n = [k for k in keys if picks[k].get()], folder.get(), 1
        lines = ["What will happen:", ""]
        for k in apps:
            name, d = APPS[k]["name"], app_dir(r, k)
            if removing and k == RP:
                lines += ["%d. REAPER LV1 (close REAPER first): remove the LV1 scripts from the action list and from" % n,
                          "   REAPER startup (the OSC surface stays)"]
            elif removing:
                lines.append("%d. %s: delete %s" % (n, name, d))
                if k == XT:
                    lines.append("   - you will be asked whether to keep your fader calibration and screen layout")
                else:
                    lines.append("   - your scenes and settings in %APPDATA%\\X32 Gain Recall are KEPT")
            elif k == XT:
                lines += ["%d. XTouch-LV1 -> %s" % (n, d),
                          "   - your fader calibration, screen layout and logs are kept if already there",
                          "   - the program asks for administrator rights each time it starts (needed so the",
                          "     LV1 follows BANK and selection)"]
            elif k == RP:
                lines += ["%d. REAPER LV1 -> REAPER settings %s (close REAPER first)" % (n, a.reaper),
                          "   - add the LV1 scripts to the action list: scenes <-> markers, track sync, meter bridge",
                          "   - start the scenes link and the meter bridge automatically with REAPER",
                          "   - add the OSC surface (receive 8000, send 9000) if missing, for the X-Touch transport"]
            else:
                lines += ["%d. X32 Gain Recall -> %s" % (n, d),
                          "   - your scenes and settings stay in %APPDATA%\\X32 Gain Recall",
                          "   - if you used 'Start with Windows' with another copy, tick it again in the app"]
            n += 1
        if apps:
            lines.append("%d. Shortcuts: Desktop, and Start menu > %s (programs, manuals, uninstall)" % (n, SUITE))
            if not removing:
                lines.append("%d. Uninstaller: %s" % (n + 1, os.path.join(suite_dir(r), "Uninstall %s.exe" % SUITE)))
        else:
            lines.append("Tick at least one program.")
        box.insert("end", "\n".join(lines) + "\n")

    def depend(key):
        """REAPER LV1 a besoin de XTouch-LV1 : à l'installation, cocher REAPER LV1 coche XTouch-LV1 (s'il n'est pas déjà
        installé) et décocher XTouch-LV1 décoche REAPER LV1 ; à la désinstallation, retirer XTouch-LV1 retire REAPER LV1."""
        if XT not in picks or RP not in picks:
            return
        if removing:
            if key == XT and picks[XT].get():
                picks[RP].set(True)
        elif XT not in have:
            if key == RP and picks[RP].get():
                picks[XT].set(True)
            if key == XT and not picks[XT].get():
                picks[RP].set(False)

    for k, v in picks.items():
        v.trace_add("write", lambda *_, k=k: (depend(k), explain()))
    folder.trace_add("write", explain)

    def chosen():
        return [k for k in keys if picks[k].get()]

    def blocked(apps):
        procs = [(APPS[k]["exe"], APPS[k]["name"]) for k in apps if APPS[k]["exe"]]
        if RP in apps or (removing and XT in apps):
            procs.append(("reaper.exe", "REAPER"))
        for image, label in procs:
            if running(image):
                return label
        return None

    def work(apps, keep, r):
        try:
            if removing:
                uninstall(r, apps, a.reaper, log, keep, not a.no_shortcuts)
            else:
                install(sources, r, apps, a.reaper, log, not a.no_shortcuts)
        except Exception as e:                             # message lisible plutôt qu'une fenêtre qui disparaît
            log("ERROR: %s" % e)
        root.after(0, lambda: (go.config(state="normal", text="Close", command=root.destroy)))

    def start():
        apps = chosen()
        if not apps:
            messagebox.showinfo(SUITE, "Tick at least one program.")
            return
        who = blocked(apps)
        if who:
            messagebox.showwarning(SUITE, "Please close %s first, then click %s again." %
                                   (who, "Uninstall" if removing else "Install"))
            return
        r = os.path.normpath(folder.get().strip())
        if not removing:
            try:                                           # dossier inscriptible ? (Program Files : non, sans admin)
                os.makedirs(r, exist_ok=True)
                probe = os.path.join(r, ".lv1suite_write_test")
                open(probe, "w").close()
                os.remove(probe)
            except OSError:
                messagebox.showwarning(SUITE, "Cannot write to %s.\nChoose another folder (for example the default "
                                              "one: %s)." % (r, default_root()))
                return
        keep = True
        if removing and XT in apps:
            keep = messagebox.askyesno(SUITE, "XTouch-LV1: keep your settings (fader calibration, screen layout)?")
        started[0] = True
        go.config(state="disabled")
        box.delete("1.0", "end")
        log("%s..." % ("Removing" if removing else "Installing"))
        threading.Thread(target=work, args=(apps, keep, r), daemon=True).start()

    go = tk.Button(bar, text="Uninstall" if removing else "Install", command=start, bg="#38c9ff", fg="#111213",
                   relief="flat", font=("Segoe UI", 11, "bold"), padx=24, pady=6,
                   state="normal" if keys else "disabled")
    go.pack(side="right")
    explain()
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Installeur LV1 Suite (XTouch-LV1, X32 Gain Recall)")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--root", default=default_root(), help="dossier des programmes (défaut %%LOCALAPPDATA%%\\Programs)")
    ap.add_argument("--reaper", default=default_reaper())
    ap.add_argument("--apps", default=None, help="silencieux : xtouch,reaper,gainrecall (défaut : tout ce qui est disponible)")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--silencieux", action="store_true", help="sans fenêtre (tests)")
    ap.add_argument("--garder-reglages", action="store_true", help="désinstallation silencieuse : garder les réglages")
    a = ap.parse_args()
    if os.path.basename(sys.executable).lower().startswith("uninstall"):
        # désinstalleur = <dossier choisi>\LV1 Suite\Uninstall LV1 Suite.exe : le dossier des programmes est au-dessus
        a.uninstall = True
        a.root = os.path.dirname(os.path.dirname(sys.executable))
    sources = bundled_sources()
    if a.silencieux:
        pool = installed(a.root) if a.uninstall else sources
        apps = [k for k in (a.apps.split(",") if a.apps else APPS) if k in pool]
        if a.uninstall:
            uninstall(a.root, apps, a.reaper, print, a.garder_reglages, not a.no_shortcuts)
        else:
            install(sources, a.root, apps, a.reaper, print, not a.no_shortcuts)
        return 0
    gui(a, sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
