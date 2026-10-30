#!/usr/bin/env python3
"""Installeur « Total Control for LV1 » (ex « LV1 Suite », demande de Joseph du 16/10/2026) : XTouch-LV1 et/ou X32 Gain Recall, au choix (cases à
cocher), un clic installe tout.

Compilé par build.py (PyInstaller onefile, les programmes sont embarqués dans l'exe). Fenêtre tkinter, textes en ANGLAIS.
Dossiers : %LOCALAPPDATA%\\Programs\\<appli>, et %LOCALAPPDATA%\\Programs\\Total Control for LV1 (désinstalleur = copie de cet exe,
installed.json = versions installées). Menu Démarrer : dossier « Total Control for LV1 » (applis, modes d'emploi, désinstalleur) ;
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
avec Windows » (tâche planifiée en 3.1, clé Run avant) est retirée à la désinstallation si elle visait l'exe installé.

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
import time

SUITE = "Total Control for LV1"                    # nom du pack (choisi par Joseph le 16/10/2026)
OLD_SUITES = ["LV1 Suite"]                         # anciens noms : dossier et menu Démarrer remplacés à l'installation
VERSION = "0.7.1"                                   # version de XTouch-LV1 (= xtouch_lv1_display.VERSION, build.py vérifie)
XT, RP, GR = "xtouch", "reaper", "gainrecall"
# RP (« REAPER LV1 », demande de Joseph) = intégration REAPER, sans dossier à elle : scripts dans <XTouch-LV1>\reaper,
# déclarés dans REAPER ; il lui faut XTouch-LV1 (le pont échange les scènes et les pistes avec les scripts).
APPS = {
    XT: {"name": "XTouch-LV1", "exe": "XTouch-LV1.exe", "manual": "MODE_EMPLOI.html",
         "about": ("X-Touch + Extender for Waves eMotion LV1", "X-Touch + Extender pour Waves eMotion LV1")},
    RP: {"name": "REAPER LV1", "exe": "reaper.exe", "manual": None, "icon": "reaper_lv1.ico",
         "about": ("REAPER 7.82 portable, downloaded from reaper.fm, set up like Tracks Live: LV1 scenes <-> markers,\n"
                   "track sync, meter bridge (needs XTouch-LV1; REAPER: 60-day evaluation, then a Cockos license)",
                   "REAPER 7.82 portable, téléchargé sur reaper.fm, réglé façon Tracks Live : scènes LV1 <-> marqueurs,\n"
                   "synchro des pistes, vumètres (avec XTouch-LV1 ; REAPER : essai 60 jours, puis licence Cockos)")},
    GR: {"name": "X32 Gain Recall", "exe": "XM32_Gain_Recall_LV1.exe", "manual": "MODE_EMPLOI.html",
         "about": ("X32 / M32 preamp gain recall for eMotion LV1", "Rappel des gains des préamplis X32 / M32 pour eMotion LV1")},
}
PERSONAL = ["xtouch_courbe_fader.json", "xtouch_ecran.json", "xtouch_couleurs.json"]
# REAPER portable (demande de Joseph : « un vrai pack ») : TÉLÉCHARGÉ sur le site de Cockos au moment de l'installation
# (la licence de REAPER ne permet de le redistribuer qu'avec un accord de distribution), installé en portable
# (/S /PORTABLE /D=), empreinte SHA-256 relevée le 16/10/2026 + signature Authenticode de Cockos vérifiées.
REAPER_VERSION = "7.82"
REAPER_URL = "https://www.reaper.fm/files/7.x/reaper782_x64-install.exe"
REAPER_SHA256 = "ae86dd8396673318a85275175dc8c1c9b0b8e090bf305f9cec920358e9d1e18f"
REAPER_EULA = "https://www.reaper.fm/purchase.php"
TEMPLATE = "LV1 Multitrack.RPP"
SCRIPTS = ["lv1_scenes.lua", "lv1_sync_tracks.lua", "lv1_meter_bridge.lua"]        # actions déclarées
STARTUP = ["lv1_scenes.lua", "lv1_meter_bridge.lua"]                              # lancées avec Reaper
BEGIN, END = "-- XTouch-LV1 begin (installer, do not edit)", "-- XTouch-LV1 end"
GR_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
GR_RUN_NAMES = ("XM32 Gain Recall LV1", "X32 Gain Recall")      # nom écrit par Gain Recall <= 3.0.1, ancien nom supposé
GR_TASK = "XM32 Gain Recall LV1"                               # tâche planifiée de Gain Recall 3.1 (TASK_NAME)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Langue de l'installeur (demande de Joseph : anglais ET français) : celle de Windows au départ, bouton EN / FR.
LANG = ["en"]


def windows_lang():
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fr" if (lid & 0x3FF) == 0x0C else "en"          # LANG_FRENCH = 0x0C
    except (AttributeError, OSError):
        return "en"


def _(en, fr):
    return fr if LANG[0] == "fr" else en


def default_root():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs")


def default_reaper():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "REAPER")


def app_dir(root, key):
    return os.path.join(root, APPS[key]["name"])


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
        out[RP] = out[XT]                                  # REAPER : téléchargé ; scripts livrés avec XTouch-LV1
    return dict((k, out[k]) for k in APPS if k in out)    # dans l'ordre d'APPS (XTouch-LV1 avant REAPER LV1)


def source_version(key, src):
    if key == XT:
        return VERSION
    if key == RP:
        return REAPER_VERSION
    try:
        with open(os.path.join(src, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def installed(root):
    """{appli: version} des applis installées (présentes sur le disque) ; installed.json relu aussi sous un ancien nom."""
    versions = {}
    for d in [suite_dir(root)] + [os.path.join(root, o) for o in OLD_SUITES]:
        try:
            with open(os.path.join(d, "installed.json"), encoding="utf-8") as f:
                versions = json.load(f)
            break
        except (OSError, ValueError):
            pass
    return {k: versions.get(k, "?") for k in APPS if os.path.exists(os.path.join(app_dir(root, k), APPS[k]["exe"]))}


def drop_old_suites(root):
    """Dossiers des anciens noms du pack (désinstalleur + installed.json, déjà relu) : retirés."""
    for o in OLD_SUITES:
        shutil.rmtree(os.path.join(root, o), ignore_errors=True)


def save_installed(root, versions):
    os.makedirs(suite_dir(root), exist_ok=True)
    with open(os.path.join(suite_dir(root), "installed.json"), "w", encoding="utf-8") as f:
        json.dump(versions, f, indent=1)


def running(image):
    """True si un processus de ce nom tourne (tasklist)."""
    if sys.platform != "win32":
        return False
    try:
        # sortie lue en octets puis décodée sans erreur possible (30/10/2026) : selon la langue et le réglage UTF-8 de
        # Windows, `text=True` pouvait lever UnicodeDecodeError -> clic sur Install sans effet (exception invisible)
        raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % image, "/NH"], capture_output=True,
                             creationflags=NO_WINDOW).stdout or b""
        out = raw.decode("utf-8", "replace") + raw.decode("cp850", "replace")
    except (OSError, ValueError, subprocess.SubprocessError):
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
    log(_("XTouch-LV1 installed in %s", "XTouch-LV1 installé dans %s") % target)
    if not getattr(sys, "frozen", False):
        return
    here = os.path.dirname(sys.executable)
    for f in PERSONAL:              # réglages posés à côté de l'installeur, ou dans dist/XTouch-LV1 (compilation de Joseph)
        for s in (os.path.join(here, f), os.path.join(here, "XTouch-LV1", f)):
            d = os.path.join(target, f)
            if os.path.exists(s) and not os.path.exists(d):
                shutil.copy2(s, d)
                log(_("Settings imported: %s", "Réglage repris : %s") % f)


def copy_gainrecall(src, target, log):
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(target, name)
        if os.path.isdir(s):                               # assets/ (logo du mode d'emploi)
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    log(_("X32 Gain Recall installed in %s (scenes and settings stay in %%APPDATA%%\\X32 Gain Recall)",
          "X32 Gain Recall installé dans %s (scènes et réglages restent dans %%APPDATA%%\\X32 Gain Recall)") % target)


def run_value(name):
    """Valeur de la clé Run (HKCU) de ce nom, ou None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GR_RUN_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def drop_run_value(name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GR_RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
        return True
    except OSError:
        return False


def schtasks(*args):
    """(code, sortie) de schtasks, sans fenêtre."""
    try:
        r = subprocess.run(["schtasks"] + list(args), capture_output=True, text=True, creationflags=NO_WINDOW, timeout=20)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def schtasks_admin(*args):
    """schtasks en administrateur (UNE demande UAC) : code de sortie, ou None si l'UAC est refusée / impossible."""
    import ctypes
    import ctypes.wintypes as wt

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND), ("lpVerb", wt.LPCWSTR),
                    ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD), ("hIcon", wt.HANDLE),
                    ("hProcess", wt.HANDLE)]
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x40, lpVerb="runas", lpFile="schtasks.exe",   # SEE_MASK_NOCLOSEPROCESS
              lpParameters=subprocess.list2cmdline(args), nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)) or not sei.hProcess:
        return None
    k32 = ctypes.windll.kernel32
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.WaitForSingleObject(sei.hProcess, 30000)
    code = wt.DWORD()
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    return code.value


def task_exe(xml):
    """Exe lancé par une tâche planifiée (XML de « schtasks /Query /XML »), ou None (même lecture que Gain Recall)."""
    m = re.search(r"<Command>(.*?)</Command>", xml or "", re.S)
    if not m:
        return None
    return (m.group(1).strip().strip('"').replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
            .replace("&amp;", "&"))


def gainrecall_autostart(target, log):
    """Désinstallation : retire le « lancer avec Windows » de Gain Recall s'il lance l'exe installé (pas une autre
    copie). 3.1 (exe administrateur) : tâche planifiée GR_TASK, créée en administrateur -> sa suppression demande les
    droits (essai du 20/10 : sans admin, même la création est refusée) : UNE demande UAC, seulement si elle vise cet exe ;
    refusée -> rien de supprimé, consigne. <= 3.0.1 : valeur de la clé Run (nom corrigé le 20/10 : l'installeur cherchait
    « X32 Gain Recall », Gain Recall écrit « XM32 Gain Recall LV1 »)."""
    if sys.platform != "win32":
        return
    exe = os.path.join(target, APPS[GR]["exe"]).lower()
    for name in GR_RUN_NAMES:
        cur = run_value(name)
        if cur and exe in cur.lower() and drop_run_value(name):
            log(_("X32 Gain Recall: removed from Windows startup", "X32 Gain Recall : retiré du démarrage de Windows"))
    code, out = schtasks("/Query", "/TN", GR_TASK, "/XML")
    hint = _("   uncheck \"Launch with Windows\" in X32 Gain Recall, or delete the task \"%s\" in Task Scheduler",
             "   décocher « Lancer avec Windows » dans X32 Gain Recall, ou supprimer la tâche « %s » du Planificateur de tâches") % GR_TASK
    if code != 0:
        if "access" in out.lower() or "accès" in out.lower():        # elle existe mais ne se lit pas : pas à l'aveugle
            log(_("X32 Gain Recall: startup task not checked (access denied):",
                  "X32 Gain Recall : tâche de démarrage pas vérifiée (accès refusé) :"))
            log(hint)
        return
    if (task_exe(out) or "").lower() != exe:
        return                                                         # une autre copie de Gain Recall : on n'y touche pas
    if schtasks("/Delete", "/TN", GR_TASK, "/F")[0] != 0:
        log(_("X32 Gain Recall: administrator rights requested to remove its startup task...",
              "X32 Gain Recall : droits administrateur demandés pour retirer sa tâche de démarrage..."))
        schtasks_admin("/Delete", "/TN", GR_TASK, "/F")
    if schtasks("/Query", "/TN", GR_TASK)[0] == 0:
        log(_("X32 Gain Recall: startup task NOT removed:", "X32 Gain Recall : tâche de démarrage PAS retirée :"))
        log(hint)
    else:
        log(_("X32 Gain Recall: startup task removed", "X32 Gain Recall : tâche de démarrage retirée"))


def shortcuts(root, log):
    """Raccourcis selon ce qui est installé : dossier SUITE du menu Démarrer refait, un raccourci Bureau par appli
    installée (retiré pour les autres). REAPER LV1 : icône rouge à lui (le distinguer d'un REAPER normal)."""
    if sys.platform != "win32":
        return
    progs = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    menu = os.path.join(progs, SUITE)
    shutil.rmtree(menu, ignore_errors=True)
    shutil.rmtree(os.path.join(progs, "XTouch-LV1"), ignore_errors=True)     # ancien dossier (1re version)
    for o in OLD_SUITES:                                                      # anciens noms du pack
        shutil.rmtree(os.path.join(progs, o), ignore_errors=True)
    have = installed(root)
    uninst = os.path.join(suite_dir(root), "Uninstall %s.exe" % SUITE)
    ps = "$d=[Environment]::GetFolderPath('Desktop');$w=New-Object -ComObject WScript.Shell;"
    links = []                                             # (raccourci, cible, dossier, icône)
    for key, app in APPS.items():
        desk = "(Join-Path $d '%s.lnk')" % app["name"]
        if key not in have:
            ps += "Remove-Item -LiteralPath %s -ErrorAction SilentlyContinue;" % desk
            continue
        d = app_dir(root, key)
        icon = os.path.join(d, app["icon"]) if app.get("icon") else None
        links += [(desk, os.path.join(d, app["exe"]), d, icon),
                  ("'%s'" % os.path.join(menu, app["name"] + ".lnk"), os.path.join(d, app["exe"]), d, icon)]
        if app["manual"]:
            links.append(("'%s'" % os.path.join(menu, app["name"] + " Manual.lnk"), os.path.join(d, app["manual"]), d,
                          None))
    if have and os.path.exists(uninst):
        links.append(("'%s'" % os.path.join(menu, "Uninstall %s.lnk" % SUITE), uninst, suite_dir(root), None))
    if have:
        os.makedirs(menu, exist_ok=True)
    q = lambda s: s.replace("'", "''")
    for lnk, path, wd, icon in links:
        if os.path.exists(path):
            ps += "$s=$w.CreateShortcut(%s);$s.TargetPath='%s';$s.WorkingDirectory='%s';" % (lnk, q(path), q(wd))
            if icon and os.path.exists(icon):
                ps += "$s.IconLocation='%s,0';" % q(icon)
            ps += "$s.Save();"
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW)
    log(_("Shortcuts updated (Desktop, Start menu > %s)", "Raccourcis mis à jour (Bureau, menu Démarrer > %s)") % SUITE)


# ---------------------------------------------------------------- Reaper

def command_id(path):
    return "RS" + hashlib.sha1(path.lower().encode("utf-8")).hexdigest()


def reaper_actions(reaper, target, log, remove=False):
    """Déclare les scripts (dans <XTouch-LV1>\\reaper : le pont y échange ses fichiers) dans reaper-kb.ini de `reaper`."""
    kb = os.path.join(reaper, "reaper-kb.ini")
    lines = [l for l in read_lines(kb) if not re.search(r'"Custom: lv1_[a-z_]+\.lua"', l)]
    ids = {}
    if not remove:
        for s in SCRIPTS:
            path = os.path.join(target, "reaper", s)
            ids[s] = command_id(path)
            lines.append('SCR 4 0 %s "Custom: %s" %s' % (ids[s], s, ('"%s"' % path) if " " in path else path))
    if lines or os.path.exists(kb):
        write_lines(kb, lines)
    log(_("REAPER actions removed", "Actions REAPER retirées") if remove else
        _("REAPER actions registered: ", "Actions REAPER déclarées : ") + ", ".join(SCRIPTS))
    return ids


def reaper_startup(reaper, ids, log, remove=False, firstrun=None):
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
        if firstrun:                                       # présentation façon Tracks Live (une seule fois)
            lines.append("dofile([[%s]])" % firstrun)
        for s in STARTUP:
            lines.append('do local c = reaper.NamedCommandLookup("_%s") if c ~= 0 then reaper.Main_OnCommand(c, 0) end'
                         ' end  -- %s' % (ids[s], s))
        lines += [END]
    if any(l.strip() for l in lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_lines(path, lines)
    elif os.path.exists(path):
        os.remove(path)
    log(_("REAPER startup: removed", "Démarrage de REAPER : retiré") if remove else
        _("REAPER startup: scenes link + meter bridge start with REAPER",
          "Démarrage de REAPER : lien des scènes + vumètres lancés avec REAPER"))


def ini_set(lines, section, key, value):
    """Fixe key=value dans [section] (nom de section sans tenir compte de la casse ; créée au besoin)."""
    head = None
    for i, l in enumerate(lines):
        if l.strip().lower() == "[%s]" % section.lower():
            head = i
            break
    if head is None:
        lines += ["[%s]" % section, "%s=%s" % (key, value)]
        return
    end = next((j for j in range(head + 1, len(lines)) if lines[j].startswith("[")), len(lines))
    for j in range(head + 1, end):
        if lines[j].split("=", 1)[0] == key:
            lines[j] = "%s=%s" % (key, value)
            return
    while end > head + 1 and not lines[end - 1].strip():      # à la fin de la section (avant les lignes vides)
        end -= 1
    lines.insert(end, "%s=%s" % (key, value))


def ini_section(lines, section):
    """Lignes clé=valeur de [section] ([] si absente)."""
    out, inside = [], False
    for l in lines:
        if l.startswith("["):
            inside = l.strip().lower() == "[%s]" % section.lower()
        elif inside and "=" in l:
            out.append(l)
    return out


def reaper_osc(lines, log):
    """Surface OSC du transport X-Touch (réception 8000, envoi 127.0.0.1:9000) si aucune n'écoute sur 8000."""
    surf = [l for l in ini_section(lines, "reaper") if re.match(r"csurf_\d+=", l)]
    if any(l.split("=", 1)[1].startswith("OSC ") and " 8000 " in l for l in surf):
        log(_("REAPER OSC (port 8000): already configured", "OSC de REAPER (port 8000) : déjà configuré"))
        return
    n = len(surf)
    ini_set(lines, "reaper", "csurf_%d" % n, 'OSC "XTouch-LV1" 3 8000 "127.0.0.1" 9000 1024 10 ""')
    ini_set(lines, "reaper", "csurf_cnt", str(n + 1))
    log(_("REAPER OSC surface added (receive 8000, send 127.0.0.1:9000)",
          "Surface OSC ajoutée dans REAPER (réception 8000, envoi 127.0.0.1:9000)"))


def documents_dir():
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:     # CSIDL_PERSONAL
            return buf.value
    except (AttributeError, OSError):
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def download_reaper(dest, log, setup=None):
    """Installeur officiel de REAPER : téléchargé sur reaper.fm (ou `setup` local), empreinte et signature vérifiées."""
    if setup:
        setup = os.path.abspath(setup)
    else:
        import urllib.request
        setup = os.path.join(dest, "reaper_setup.exe")
        log(_("Downloading REAPER %s from reaper.fm...", "Téléchargement de REAPER %s sur reaper.fm...") % REAPER_VERSION)
        req = urllib.request.Request(REAPER_URL, headers={"User-Agent": "Total-Control-LV1-Installer"})
        with urllib.request.urlopen(req, timeout=60) as r, open(setup, "wb") as f:
            total, got, step = int(r.headers.get("Content-Length") or 0), 0, 25
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                f.write(block)
                got += len(block)
                if total and got * 100 // total >= step:
                    log("  %d %%" % step)
                    step += 25
    h = hashlib.sha256()
    with open(setup, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != REAPER_SHA256:
        raise RuntimeError(_("REAPER installer: unexpected file (checksum), installation stopped",
                             "Installeur de REAPER : fichier inattendu (empreinte), installation arrêtée"))
    if sys.platform == "win32":
        ps = ("$s=Get-AuthenticodeSignature -LiteralPath '%s';"
              "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*Cockos Incorporated*'){'ok'}"
              % setup.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
        if "ok" not in out:
            raise RuntimeError(_("REAPER installer: invalid Cockos signature, installation stopped",
                                 "Installeur de REAPER : signature Cockos invalide, installation arrêtée"))
    log(_("REAPER installer verified (checksum + Cockos signature)",
          "Installeur de REAPER vérifié (empreinte + signature Cockos)"))
    return setup


def install_reaper_binaries(target, log, setup=None):
    """REAPER portable dans `target` (/S /PORTABLE /D=). Sa configuration (reaper.ini…) est gardée d'une réinstallation
    à l'autre : sauvegardée avant, remise après (l'installeur de REAPER peut réécrire reaper.ini)."""
    target = os.path.normpath(os.path.abspath(target))      # /D= de NSIS : chemin complet, barres Windows
    os.makedirs(target, exist_ok=True)
    keep = {}
    for f in ("reaper.ini", "reaper-kb.ini", "reaper-extstate.ini"):
        p = os.path.join(target, f)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                keep[f] = fh.read()
    import tempfile
    tmp = tempfile.mkdtemp(prefix="totalcontrol_")
    try:
        exe = download_reaper(tmp, log, setup)
        log(_("Installing REAPER %s (portable) in %s...", "Installation de REAPER %s (portable) dans %s...")
            % (REAPER_VERSION, target))
        # NSIS : /D= en DERNIER et SANS guillemets, même avec des espaces (liste Python = guillemets ajoutés -> ignoré)
        r = subprocess.run('"%s" /S /PORTABLE /D=%s' % (exe, target), creationflags=NO_WINDOW)
        if r.returncode or not os.path.exists(os.path.join(target, "reaper.exe")):
            raise RuntimeError(_("REAPER installation failed (code %d)", "Échec de l'installation de REAPER (code %d)")
                               % r.returncode)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f, data in keep.items():
        if len(data) > 64:                                 # pas le petit reaper.ini « portable » de départ
            with open(os.path.join(target, f), "wb") as fh:
                fh.write(data)


def reaper_portable_config(rdir, xt_dir, personal, log, icon_src=None):
    """Préréglage du REAPER portable, façon Tracks Live 2 (le reste est fait au 1er démarrage par lv1_firstrun.lua) :
    scripts LV1 déclarés et lancés au démarrage, barre de vumètres ancrée dans le docker du HAUT, surface OSC, projets
    dans Documents\\REAPER LV1 Projects (jamais effacés), carte son reprise du REAPER habituel (`personal`) s'il existe."""
    ids = reaper_actions(rdir, xt_dir, log)
    reaper_startup(rdir, ids, log, firstrun=os.path.join(xt_dir, "reaper", "lv1_firstrun.lua"))
    ini = os.path.join(rdir, "reaper.ini")
    lines = read_lines(ini) or ["[REAPER]"]
    reaper_osc(lines, log)
    projects = os.path.join(documents_dir(), "REAPER LV1 Projects")
    os.makedirs(projects, exist_ok=True)
    noplug = os.path.join(rdir, "NoPlugins")
    os.makedirs(noplug, exist_ok=True)
    tmpl = os.path.join(rdir, "ProjectTemplates", TEMPLATE)
    if not os.path.exists(tmpl):                           # projet type (Joseph pourra le retoucher : jamais écrasé)
        os.makedirs(os.path.dirname(tmpl), exist_ok=True)
        write_lines(tmpl, ['<REAPER_PROJECT 0.1 "%s/win64" 0' % REAPER_VERSION, '  RECORD_PATH "Audio" ""', ">"])
    for k, v in (("mixwnd_vis", "0"), ("dockermode1", "2"), ("dockheight_t", "190"), ("defsavepath", projects),
                 ("newprojtmpl", tmpl),
                 # pas de plugins (Joseph : tout le traitement est dans la LV1) : chemins vides, pas de recherche
                 # (vides : REAPER scanne ses chemins par défaut, essai du 16/10) -> un dossier vide à lui
                 ("vstpath64", noplug), ("clap_path_win64", noplug), ("lv2path_win64", noplug)):
        ini_set(lines, "reaper", k, v)
    ini_set(lines, "REAPERdockpref", "lv1_meter_bridge.lua", "0.50000000 1")
    mine = read_lines(os.path.join(personal, "REAPER.ini")) if personal else []
    if mine and not ini_section(lines, "audioconfig"):    # carte son (ASIO SoundGrid…) du REAPER habituel
        for sec in ("audioconfig", "asiochan"):
            for l in ini_section(mine, sec):
                k, v = l.split("=", 1)
                ini_set(lines, sec, k, v)
        log(_("Audio device settings copied from your REAPER", "Réglages de la carte son repris de votre REAPER"))
    write_lines(ini, lines)
    # REAPER rajoute de lui-même les dossiers VST3 standards de Windows (essai du 16/10 : ~4 min de scan des Waves au
    # 1er démarrage) : la liste déjà scannée par le REAPER habituel évite ce scan (fichiers connus = pas rescannés)
    for f in ("reaper-vstplugins64.ini", "reaper-vstshells64.ini", "reaper-clap-win64.ini"):
        s, d = os.path.join(personal or "", f), os.path.join(rdir, f)
        if personal and os.path.exists(s) and not os.path.exists(d):
            shutil.copy2(s, d)
            log(_("Plugin list copied from your REAPER (no long scan): %s",
                  "Liste des plugins reprise de votre REAPER (pas de long scan) : %s") % f)
    ext = os.path.join(rdir, "reaper-extstate.ini")
    el = read_lines(ext)
    if not ini_section(el, "lv1_meter_bridge"):           # vumètres : docker 1 (en haut), toutes les colonnes visibles
        ini_set(el, "lv1_meter_bridge", "dock", "257")
        ini_set(el, "lv1_meter_bridge", "fit", "1")
        write_lines(ext, el)
    if icon_src and os.path.exists(icon_src):
        shutil.copy2(icon_src, os.path.join(rdir, APPS[RP]["icon"]))
    log(_("REAPER LV1 set up like Tracks Live (projects in %s)", "REAPER LV1 réglé façon Tracks Live (projets dans %s)")
        % projects)
    suite_link(xt_dir, os.path.join(rdir, "reaper.exe"))


def suite_link(xt_dir, reaper_exe, key="reaper"):
    """suite.json du pont : programmes que XTouch-LV1 lance au démarrage, "reaper" (REAPER LV1) et "gainrecall"
    (X/M32 Gain Recall, demande de Joseph du 16/10). None = retire la clé ; fichier effacé s'il ne reste rien."""
    path = os.path.join(xt_dir, "suite.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if reaper_exe:
        data[key] = reaper_exe
    else:
        data.pop(key, None)
    if data:
        os.makedirs(xt_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    elif os.path.exists(path):
        os.remove(path)


def gainrecall_link(root):
    """suite.json : chemin de Gain Recall tant que XTouch-LV1 et Gain Recall sont installés tous les deux."""
    have = installed(root)
    if XT in have:
        exe = os.path.join(app_dir(root, GR), APPS[GR]["exe"]) if GR in have else None
        suite_link(app_dir(root, XT), exe, "gainrecall")


# ---------------------------------------------------------------- étapes

def install(sources, root, apps, reaper, log, do_shortcuts=True, reaper_setup=None):
    """sources : {appli: dossier source} ; apps : applis cochées ; reaper : REAPER habituel (%APPDATA%\\REAPER : carte
    son reprise, anciens réglages LV1 retirés) ; reaper_setup : installeur de REAPER local (sinon téléchargé)."""
    root = os.path.normpath(os.path.abspath(root))
    versions = installed(root)
    apps = [k for k in APPS if k in apps]                  # XTouch-LV1 avant REAPER LV1
    if RP in apps and XT not in apps and XT not in versions:
        raise RuntimeError(_("REAPER LV1 needs XTouch-LV1: tick it too", "REAPER LV1 a besoin de XTouch-LV1 : cochez-le aussi"))
    for key in apps:
        src = sources.get(key)
        if not src or not os.path.exists(os.path.join(src, APPS[XT if key == RP else key]["exe"])):
            raise RuntimeError(_("%s: program files not found", "%s : fichiers du programme introuvables") % APPS[key]["name"])
        target = app_dir(root, key)
        if key == XT:
            copy_xtouch(src, target, log)
        elif key == RP:
            if versions.get(RP) != REAPER_VERSION or not os.path.exists(os.path.join(target, "reaper.exe")):
                install_reaper_binaries(target, log, reaper_setup)
            else:
                log(_("REAPER %s already installed: settings updated only", "REAPER %s déjà installé : réglages seulement")
                    % REAPER_VERSION)
            icon = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets",
                                APPS[RP]["icon"])
            reaper_portable_config(target, app_dir(root, XT), reaper if os.path.isdir(reaper) else None, log, icon)
            if os.path.isdir(reaper) and read_lines(os.path.join(reaper, "reaper-kb.ini")) and \
                    any("lv1_" in l for l in read_lines(os.path.join(reaper, "reaper-kb.ini"))):
                reaper_actions(reaper, target, lambda m: None, remove=True)   # ancienne version : REAPER habituel
                reaper_startup(reaper, {}, lambda m: None, remove=True)
                log(_("Your usual REAPER: LV1 scripts removed (they now live in REAPER LV1)",
                      "Votre REAPER habituel : scripts LV1 retirés (ils sont maintenant dans REAPER LV1)"))
        else:
            copy_gainrecall(src, target, log)
        versions[key] = source_version(key, src)
    save_installed(root, versions)
    gainrecall_link(root)                                  # XTouch-LV1 lance aussi Gain Recall
    drop_old_suites(root)
    if getattr(sys, "frozen", False):                      # même exe = désinstalleur
        shutil.copy2(sys.executable, os.path.join(suite_dir(root), "Uninstall %s.exe" % SUITE))
    if do_shortcuts:
        shortcuts(root, log)
    log(_("Done. Start the programs from their Desktop shortcuts (manuals: Start menu > %s).",
          "Terminé. Lancez les programmes avec leurs raccourcis du Bureau (modes d'emploi : menu Démarrer > %s).") % SUITE)


def uninstall(root, apps, reaper, log, keep_settings, do_shortcuts=True):
    root = os.path.normpath(os.path.abspath(root))
    versions = installed(root)
    if XT in apps and RP not in apps and RP in versions:
        apps = list(apps) + [RP]                           # sans XTouch-LV1, les scripts de REAPER LV1 n'existent plus
    apps = [k for k in APPS if k in apps]
    for key in apps:
        target = app_dir(root, key)
        if key == RP:
            shutil.rmtree(target, ignore_errors=True)
            suite_link(app_dir(root, XT), None)
            log(_("REAPER LV1 removed (your projects stay in %s)", "REAPER LV1 retiré (vos projets restent dans %s)")
                % os.path.join(documents_dir(), "REAPER LV1 Projects"))
        elif key == XT:
            if keep_settings:
                for name in os.listdir(target) if os.path.isdir(target) else []:
                    if name not in PERSONAL and not name.startswith("xtouch_journal_"):
                        p = os.path.join(target, name)
                        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
                log(_("XTouch-LV1 removed, settings kept in %s", "XTouch-LV1 retiré, réglages gardés dans %s") % target)
            else:
                shutil.rmtree(target, ignore_errors=True)
                log(_("XTouch-LV1 removed", "XTouch-LV1 retiré"))
        else:
            gainrecall_autostart(target, log)
            shutil.rmtree(target, ignore_errors=True)
            log(_("X32 Gain Recall removed (scenes and settings kept in %APPDATA%\\X32 Gain Recall)",
                  "X32 Gain Recall retiré (scènes et réglages gardés dans %APPDATA%\\X32 Gain Recall)"))
        versions.pop(key, None)
    left = installed(root)
    gainrecall_link(root)
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

LOG_FILE = os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"), "Total_Control_LV1_Install.log")


def log_file(msg):
    """Journal de l'installeur (%TEMP%/Total_Control_LV1_Install.log) : l'exe n'a pas de console."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def gui(a, sources):
    import tkinter as tk
    import traceback
    from tkinter import messagebox
    removing = a.uninstall
    have = installed(a.root)
    keys = [k for k in APPS if (k in have if removing else k in sources)]
    bg, fg, dim, field = "#111213", "#e9edf0", "#9aa0a6", "#1b1d20"
    root = tk.Tk()
    root.configure(bg=bg)
    log_file("installeur %s, Windows %s, langue %s" % (VERSION, sys.getwindowsversion().build
                                                       if hasattr(sys, "getwindowsversion") else "?", LANG[0]))

    def on_error(exc, val, tb):
        """Erreur dans un clic (30/10/2026, « Install ne fait rien » sous Windows 11) : affichée et journalisée au lieu
        de disparaître (pas de console)."""
        text = "".join(traceback.format_exception(exc, val, tb))
        log_file("ERREUR\n" + text)
        try:
            state["go"].config(state="normal")
        except Exception:
            pass
        messagebox.showerror(SUITE, _("Unexpected error:\n%s\n\nDetails saved in:\n%s",
                                      "Erreur inattendue :\n%s\n\nDétails enregistrés dans :\n%s") % (val, LOG_FILE),
                             parent=root)
    root.report_callback_exception = on_error
    ico = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
    if os.path.exists(ico):                                # logo de XTouch-LV1 dans la barre de titre
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass
    root.geometry("740x620")
    picks = {k: tk.BooleanVar(value=True) for k in keys}  # gardés quand on change de langue
    folder = tk.StringVar(value=a.root)
    state = {"started": False, "box": None, "go": None}

    def log(msg):
        log_file(msg)

        def put():
            box = state["box"]
            box.insert("end", msg + "\n")
            box.see("end")
        root.after(0, put)

    def explain(*_args):
        """Étapes de ce qui va être fait, selon les cases cochées et le dossier (avant de cliquer)."""
        box = state["box"]
        if state["started"] or box is None:
            return
        box.delete("1.0", "end")
        apps, r, n = [k for k in keys if picks[k].get()], folder.get(), 1
        lines = [_("What will happen:", "Ce qui va être fait :"), ""]
        for k in apps:
            name, d = APPS[k]["name"], app_dir(r, k)
            if removing and k == RP:
                lines += ["%d. " % n + _("REAPER LV1 (close it first): delete %s", "REAPER LV1 (fermez-le avant) : supprimer %s")
                          % d,
                          _("   - your projects and recordings in Documents\\REAPER LV1 Projects are KEPT",
                            "   - vos projets et enregistrements dans Documents\\REAPER LV1 Projects sont GARDÉS"),
                          _("   - your usual REAPER (if any) is not touched", "   - votre REAPER habituel (s'il y en a un) n'est pas touché")]
            elif removing:
                lines.append("%d. " % n + _("%s: delete %s", "%s : supprimer %s") % (name, d))
                if k == XT:
                    lines.append(_("   - you will be asked whether to keep your fader calibration and screen layout",
                                   "   - on vous demandera s'il faut garder la calibration des faders et le réglage d'écran"))
                else:
                    lines.append(_("   - your scenes and settings in %APPDATA%\\X32 Gain Recall are KEPT",
                                   "   - vos scènes et réglages dans %APPDATA%\\X32 Gain Recall sont GARDÉS"))
            elif k == XT:
                lines += ["%d. XTouch-LV1 -> %s" % (n, d),
                          _("   - your fader calibration, screen layout and logs are kept if already there",
                            "   - calibration des faders, réglage d'écran et journaux gardés s'ils sont déjà là"),
                          _("   - the program asks for administrator rights each time it starts (needed so the",
                            "   - le programme demande les droits administrateur à chaque lancement (pour que la"),
                          _("     LV1 follows BANK and selection)", "     LV1 suive BANK et la sélection)")]
            elif k == RP:
                lines += ["%d. REAPER LV1 -> %s" % (n, d),
                          _("   - download REAPER %s from reaper.fm (17 MB, official Cockos installer, checked) and",
                            "   - télécharger REAPER %s sur reaper.fm (17 Mo, installeur officiel Cockos, vérifié) et")
                          % REAPER_VERSION,
                          _("     install it as a separate PORTABLE copy: your usual REAPER is not changed",
                            "     l'installer en copie PORTABLE séparée : votre REAPER habituel n'est pas modifié"),
                          _("   - set it up like Tracks Live: tracks + meter bridge on top, mixer and master hidden,",
                            "   - le régler façon Tracks Live : pistes + vumètres en haut, mixage et master cachés,"),
                          _("     transport on top, LV1 scenes <-> markers, track sync, OSC for the X-Touch transport",
                            "     transport en haut, scènes LV1 <-> marqueurs, synchro des pistes, OSC du transport X-Touch"),
                          _("   - projects saved in Documents\\REAPER LV1 Projects; audio device copied from your REAPER",
                            "   - projets dans Documents\\REAPER LV1 Projects ; carte son reprise de votre REAPER"),
                          _("   - REAPER is Cockos software: 60-day evaluation, then a REAPER license is needed",
                            "   - REAPER est un logiciel Cockos : essai de 60 jours, puis une licence REAPER est nécessaire")]
            else:
                lines += ["%d. X32 Gain Recall -> %s" % (n, d),
                          _("   - your scenes and settings stay in %APPDATA%\\X32 Gain Recall",
                            "   - vos scènes et réglages restent dans %APPDATA%\\X32 Gain Recall"),
                          _("   - if you used 'Start with Windows' with another copy, tick it again in the app",
                            "   - si « Lancer avec Windows » était coché avec une autre copie, recochez-le dans l'appli")]
            n += 1
        if apps:
            lines.append("%d. " % n + _("Shortcuts: Desktop, and Start menu > %s (programs, manuals, uninstall)",
                                        "Raccourcis : Bureau, et menu Démarrer > %s (programmes, modes d'emploi, désinstallation)")
                         % SUITE)
            if not removing:
                lines.append("%d. " % (n + 1) + _("Uninstaller: %s", "Désinstalleur : %s")
                             % os.path.join(suite_dir(r), "Uninstall %s.exe" % SUITE))
        else:
            lines.append(_("Tick at least one program.", "Cochez au moins un programme."))
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
        v.trace_add("write", lambda *_args, k=k: (depend(k), explain()))
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

    def launch_xtouch(r):
        """Bouton « Lancer XTouch-LV1 » (Joseph, 18/10) : ShellExecute (os.startfile) car l'exe demande les droits
        administrateur (UAC) ; un simple Popen échouerait (erreur 740). Puis l'installeur se ferme."""
        try:
            os.startfile(os.path.join(app_dir(r, XT), APPS[XT]["exe"]))
        except OSError as e:
            messagebox.showwarning(SUITE, _("Cannot start XTouch-LV1: %s", "Impossible de lancer XTouch-LV1 : %s") % e)
            return
        root.destroy()

    def finish(r, ok):
        state["go"].config(state="normal", text=_("Close", "Fermer"), command=root.destroy)
        if ok and not removing and XT in installed(r):
            state["go"].config(bg="#3a3e43", fg=fg)
            tk.Button(state["bar"], text=_("Launch XTouch-LV1", "Lancer XTouch-LV1"), command=lambda: launch_xtouch(r),
                      bg="#38c9ff", fg="#111213", relief="flat", font=("Segoe UI", 11, "bold"), padx=24,
                      pady=6).pack(side="right", padx=(0, 10))

    def work(apps, keep, r):
        ok = False
        try:
            if removing:
                uninstall(r, apps, a.reaper, log, keep, not a.no_shortcuts)
            else:
                install(sources, r, apps, a.reaper, log, not a.no_shortcuts, a.reaper_setup)
            ok = True
        except Exception as e:                             # message lisible plutôt qu'une fenêtre qui disparaît
            log(_("ERROR: %s", "ERREUR : %s") % e)
        root.after(0, lambda: finish(r, ok))

    def start():
        apps = chosen()
        if not apps:
            messagebox.showinfo(SUITE, _("Tick at least one program.", "Cochez au moins un programme."))
            return
        who = blocked(apps)
        if who:
            messagebox.showwarning(SUITE, _("Please close %s first, then click %s again.",
                                            "Fermez d'abord %s, puis cliquez à nouveau sur %s.")
                                   % (who, go_label()))
            return
        r = os.path.normpath(folder.get().strip())
        if not removing:
            try:                                           # dossier inscriptible ? (Program Files : non, sans admin)
                os.makedirs(r, exist_ok=True)
                probe = os.path.join(r, ".totalcontrol_write_test")
                open(probe, "w").close()
                os.remove(probe)
            except OSError:
                messagebox.showwarning(SUITE, _("Cannot write to %s.\nChoose another folder (for example the default "
                                                "one: %s).",
                                                "Impossible d'écrire dans %s.\nChoisissez un autre dossier (par exemple "
                                                "celui par défaut : %s).") % (r, default_root()))
                return
        if not removing and RP in apps:                    # licence de REAPER (son installeur est lancé en silencieux)
            if not messagebox.askyesno(SUITE, _(
                    "REAPER is downloaded from reaper.fm and installed silently.\n\nREAPER is commercial software by "
                    "Cockos: you may evaluate it for 60 days, then you need a REAPER license (reaper.fm). Its license "
                    "(EULA.txt) will be in the REAPER LV1 folder.\n\nDo you accept the REAPER license terms?",
                    "REAPER est téléchargé sur reaper.fm et installé sans fenêtre.\n\nREAPER est un logiciel commercial "
                    "de Cockos : essai de 60 jours, ensuite une licence REAPER est nécessaire (reaper.fm). Sa licence "
                    "(EULA.txt) sera dans le dossier REAPER LV1.\n\nAcceptez-vous la licence de REAPER ?")):
                return
        keep = True
        if removing and XT in apps:
            keep = messagebox.askyesno(SUITE, _("XTouch-LV1: keep your settings (fader calibration, screen layout)?",
                                                "XTouch-LV1 : garder vos réglages (calibration des faders, réglage d'écran) ?"))
        state["started"] = True
        lang_btn.config(state="disabled")
        state["go"].config(state="disabled")
        state["box"].delete("1.0", "end")
        log(_("Removing...", "Désinstallation...") if removing else _("Installing...", "Installation..."))
        threading.Thread(target=work, args=(apps, keep, r), daemon=True).start()

    def go_label():
        return _("Uninstall", "Désinstaller") if removing else _("Install", "Installer")

    body = tk.Frame(root, bg=bg)

    def build():
        """(Re)construit la fenêtre dans la langue courante ; cases et dossier sont gardés."""
        nonlocal body
        body.destroy()
        body = tk.Frame(root, bg=bg)
        body.pack(fill="both", expand=True)
        root.title("%s %s" % (SUITE, _("Uninstall", "Désinstallation") if removing else _("Setup", "Installation")))
        lang_btn.config(text="FR" if LANG[0] == "en" else "EN")
        tk.Label(body, text=_("Choose what to %s:", "Choisissez ce qu'il faut %s :")
                 % (_("remove", "désinstaller") if removing else _("install", "installer")),
                 fg=dim, bg=bg, font=("Segoe UI", 10)).pack(anchor="w", padx=16)
        for k in keys:
            app = APPS[k]
            new = "v" + (have[k] if removing else source_version(k, sources[k]))
            cur = "" if removing else (_("  (installed: v%s)", "  (installé : v%s)") % have[k] if k in have else "")
            tk.Checkbutton(body, text="%s  %s%s\n%s" % (app["name"], new, cur, _(*app["about"])), variable=picks[k],
                           justify="left", anchor="w", fg=fg, bg=bg, selectcolor=field, activebackground=bg,
                           activeforeground=fg, font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(8, 0))
        if not keys:
            tk.Label(body, text=_("Nothing to remove.", "Rien à désinstaller.") if removing else
                     _("Nothing to install.", "Rien à installer."), fg=fg, bg=bg,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=8)
        if not removing:                                   # choix du dossier (demande de Joseph)
            row = tk.Frame(body, bg=bg)
            row.pack(fill="x", padx=16, pady=(10, 0))
            tk.Label(row, text=_("Install folder:", "Dossier d'installation :"), fg=dim, bg=bg,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Entry(row, textvariable=folder, bg=field, fg=fg, insertbackground=fg, relief="flat",
                     font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, padx=8, ipady=3)

            def browse():
                from tkinter import filedialog
                d = filedialog.askdirectory(initialdir=folder.get(), title=_("Install folder", "Dossier d'installation"))
                if d:
                    folder.set(os.path.normpath(d))
            tk.Button(row, text=_("Browse…", "Parcourir…"), command=browse, bg="#3a3e43", fg=fg, relief="flat",
                      font=("Segoe UI", 9)).pack(side="right")
        state["box"] = tk.Text(body, height=12, bg=field, fg=fg, relief="flat", font=("Consolas", 9), wrap="word")
        state["box"].pack(fill="both", expand=True, padx=16, pady=10)
        bar = tk.Frame(body, bg=bg)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        state["bar"] = bar
        state["go"] = tk.Button(bar, text=go_label(), command=start, bg="#38c9ff", fg="#111213", relief="flat",
                                font=("Segoe UI", 11, "bold"), padx=24, pady=6, state="normal" if keys else "disabled")
        state["go"].pack(side="right")
        explain()

    def toggle_lang():
        LANG[0] = "fr" if LANG[0] == "en" else "en"
        build()

    head = tk.Frame(root, bg=bg)
    head.pack(fill="x", padx=16, pady=(14, 0))
    tk.Label(head, text=SUITE, fg=fg, bg=bg, font=("Segoe UI", 16, "bold")).pack(side="left")
    lang_btn = tk.Button(head, command=toggle_lang, bg="#3a3e43", fg=fg, relief="flat", width=4,
                         font=("Segoe UI", 9, "bold"))
    lang_btn.pack(side="right")
    build()
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Installeur Total Control for LV1 (XTouch-LV1, REAPER LV1, X32 Gain Recall)")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--root", default=default_root(), help="dossier des programmes (défaut %%LOCALAPPDATA%%\\Programs)")
    ap.add_argument("--reaper", default=default_reaper())
    ap.add_argument("--apps", default=None, help="silencieux : xtouch,reaper,gainrecall (défaut : tout ce qui est disponible)")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--langue", choices=["en", "fr"], help="langue de l'installeur (défaut : celle de Windows)")
    ap.add_argument("--silencieux", action="store_true", help="sans fenêtre (tests)")
    ap.add_argument("--reaper-setup", help="installeur de REAPER local (sinon téléchargé sur reaper.fm)")
    ap.add_argument("--garder-reglages", action="store_true", help="désinstallation silencieuse : garder les réglages")
    a = ap.parse_args()
    if os.path.basename(sys.executable).lower().startswith("uninstall"):
        # désinstalleur = <dossier choisi>\<SUITE>\Uninstall <SUITE>.exe : le dossier des programmes est au-dessus
        a.uninstall = True
        a.root = os.path.dirname(os.path.dirname(sys.executable))
    sources = bundled_sources()
    LANG[0] = a.langue or windows_lang()
    if a.silencieux:
        pool = installed(a.root) if a.uninstall else sources
        apps = [k for k in (a.apps.split(",") if a.apps else APPS) if k in pool]
        if a.uninstall:
            uninstall(a.root, apps, a.reaper, print, a.garder_reglages, not a.no_shortcuts)
        else:
            install(sources, a.root, apps, a.reaper, print, not a.no_shortcuts, a.reaper_setup)
        return 0
    gui(a, sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
