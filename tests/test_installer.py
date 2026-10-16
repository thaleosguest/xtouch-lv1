"""Test : installeur LV1 Suite sur des dossiers temporaires (faux programmes, faux REAPER habituel ; l'installation du
REAPER portable est simulée : pas de téléchargement).
- XTouch-LV1 seul : programme copié, rien d'autre ; REAPER LV1 sans XTouch-LV1 : refusé ;
- XTouch-LV1 + REAPER LV1 + Gain Recall (2 fois, idempotent) : REAPER portable préréglé (scripts déclarés, __startup.lua
  avec lv1_firstrun, OSC, docker du haut, projet type, chemins de plugins vides, vumètres ancrés, carte son reprise du
  REAPER habituel), suite.json du pont ; REAPER habituel : anciennes lignes lv1_* retirées, le reste gardé ;
  réglages XTouch-LV1 jamais écrasés ;
- désinstallation de XTouch-LV1 (réglages gardés) : REAPER LV1 retiré aussi ; Gain Recall reste ; puis Gain Recall."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import installer as I

root = tempfile.mkdtemp(prefix="inst_")
progs, rp, stage = (os.path.join(root, d) for d in ("Programs dir", "REAPER", "stage"))
xt_src, gr_src = os.path.join(stage, "xtouch"), os.path.join(stage, "gainrecall")
for d in (os.path.join(xt_src, "reaper"), os.path.join(xt_src, "_internal"), gr_src, os.path.join(rp, "Scripts")):
    os.makedirs(d)
def put(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f: f.write(s)
def get(p):
    with open(p, encoding="utf-8", newline="") as f: return f.read()
put(os.path.join(xt_src, "XTouch-LV1.exe"), "exe")
put(os.path.join(xt_src, "_internal", "x.dll"), "dll")
for s in I.SCRIPTS + ["lv1_common.lua", "lv1_firstrun.lua"]: put(os.path.join(xt_src, "reaper", s), "-- " + s)
put(os.path.join(xt_src, "xtouch_ecran.json"), "NEW")
put(os.path.join(gr_src, "XM32_Gain_Recall_LV1.exe"), "gr")
put(os.path.join(gr_src, "version.txt"), "3.0.0")
os.makedirs(os.path.join(gr_src, "assets")); put(os.path.join(gr_src, "assets", "logo.svg"), "<svg/>")
xt_dir, rdir = os.path.join(progs, "XTouch-LV1"), os.path.join(progs, "REAPER LV1")
os.makedirs(xt_dir); put(os.path.join(xt_dir, "xtouch_ecran.json"), "MINE")         # réglage déjà là
# REAPER habituel : ancienne version (lignes lv1_* déclarées, bloc de démarrage) + carte son ASIO
put(os.path.join(rp, "reaper-kb.ini"), 'SCR 4 0 RSaaa "Custom: lyrics.lua" Cockos/lyrics.lua\r\n'
    'SCR 4 0 RSbbb "Custom: lv1_scenes.lua" C:\\old\\reaper\\lv1_scenes.lua\r\n')
put(os.path.join(rp, "REAPER.ini"), "[reaper]\r\nfoo=1\r\n[audioconfig]\r\nmode=3\r\nasio_driver_name=\"Waves SoundGrid ASIO\"\r\n"
    "[asiochan]\r\nWaves SoundGrid ASIO=0 127 0 127\r\n")
put(os.path.join(rp, "Scripts", "__startup.lua"), "-- user stuff\r\n" + I.BEGIN + "\r\nold()\r\n" + I.END + "\r\n")

runs = []
def fake_reaper(target, log, setup=None):                 # REAPER portable simulé
    runs.append(target)
    os.makedirs(target, exist_ok=True)
    put(os.path.join(target, "reaper.exe"), "reaper")
    if not os.path.exists(os.path.join(target, "reaper.ini")):
        put(os.path.join(target, "reaper.ini"), "[REAPER]\r\nwnd_state=0\r\n")
I.install_reaper_binaries = fake_reaper

src = {I.XT: xt_src, I.RP: xt_src, I.GR: gr_src}
out, ok, why = [], True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

try:                                                    # REAPER LV1 seul, XTouch-LV1 pas installé : refusé
    I.install(src, progs, [I.RP], rp, out.append, do_shortcuts=False); check("RP seul refusé", False)
except RuntimeError:
    pass
I.install(src, progs, [I.XT], rp, out.append, do_shortcuts=False)
check("XT seul", I.installed(progs) == {I.XT: "0.1"} and not os.path.exists(rdir) and "RSbbb" in get(os.path.join(rp, "reaper-kb.ini")))
for _ in range(2):
    I.install(src, progs, [I.XT, I.RP, I.GR], rp, out.append, do_shortcuts=False)
check("REAPER installé une fois", len(runs) == 1)
kb = get(os.path.join(rdir, "reaper-kb.ini"))
ini = get(os.path.join(rdir, "reaper.ini"))
st = get(os.path.join(rdir, "Scripts", "__startup.lua"))
ext = get(os.path.join(rdir, "reaper-extstate.ini"))
check("kb", kb.count("lv1_") == 6 and kb.count('"' + xt_dir) == 3)
check("startup", st.count(I.BEGIN) == 1 and st.count("NamedCommandLookup") == 2 and "lv1_firstrun.lua" in st)
check("ini", 'csurf_0=OSC "XTouch-LV1" 3 8000' in ini and "csurf_cnt=1" in ini and "dockermode1=2" in ini
      and "mixwnd_vis=0" in ini and "newprojtmpl=" + os.path.join(rdir, "ProjectTemplates", I.TEMPLATE) in ini
      and "vstpath64=" + os.path.join(rdir, "NoPlugins") in ini and "wnd_state=0" in ini)
check("carte son", 'asio_driver_name="Waves SoundGrid ASIO"' in ini and "Waves SoundGrid ASIO=0 127 0 127" in ini)
check("vumètres", "dock=257" in ext and "lv1_meter_bridge.lua=0.50000000 1" in ini)
check("projet type", 'RECORD_PATH "Audio"' in get(os.path.join(rdir, "ProjectTemplates", I.TEMPLATE)))
check("suite.json", os.path.join(rdir, "reaper.exe") in get(os.path.join(xt_dir, "suite.json")).replace("\\\\", "\\"))
pk, ps_ = get(os.path.join(rp, "reaper-kb.ini")), get(os.path.join(rp, "Scripts", "__startup.lua"))
check("REAPER habituel nettoyé", "lv1_" not in pk and "lyrics" in pk and I.BEGIN not in ps_ and "user stuff" in ps_)
check("réglage gardé", get(os.path.join(xt_dir, "xtouch_ecran.json")) == "MINE")
check("crlf", "\n" not in kb.replace("\r\n", ""))
check("installed", I.installed(progs) == {I.XT: "0.1", I.RP: I.REAPER_VERSION, I.GR: "3.0.0"})

I.uninstall(progs, [I.XT], rp, out.append, keep_settings=True, do_shortcuts=False)
check("désinst. XT -> RP retiré", not os.path.exists(rdir) and not os.path.exists(os.path.join(xt_dir, "suite.json")))
check("réglages gardés", sorted(os.listdir(xt_dir)) == ["xtouch_ecran.json"])
check("GR reste", I.installed(progs) == {I.GR: "3.0.0"} and os.path.isdir(I.suite_dir(progs)))
I.uninstall(progs, [I.GR], rp, out.append, keep_settings=True, do_shortcuts=False)
check("tout retiré", I.installed(progs) == {} and not os.path.exists(os.path.join(progs, "X32 Gain Recall"))
      and not os.path.isdir(I.suite_dir(progs)))
print("\n".join(out))
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
