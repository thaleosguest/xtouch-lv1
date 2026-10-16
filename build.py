#!/usr/bin/env python3
"""Compilation de l'installeur « LV1 Suite » : dist/LV1_Suite_Install.exe (XTouch-LV1 et/ou X32 Gain Recall, au choix).

    py build.py                          # Gain Recall = release GitHub GR_TAG (téléchargée une fois, empreinte vérifiée)
    py build.py --gain-recall CHEMIN.exe # ou un exe local de Gain Recall
    py build.py --sans-gain-recall       # XTouch-LV1 seul

1. PyInstaller compile le pont (xtouch_lv1_display.py, overlay Qt compris : « XTouch-LV1.exe --overlay ») en dossier
   (onedir, console, droits administrateur demandés au lancement) ;
2. build/stage/xtouch = ce dossier + reaper/*.lua + LISEZMOI.md + MODE_EMPLOI.html + exemple de couleurs ;
   build/stage/gainrecall = XM32_Gain_Recall_LV1.exe + MODE_EMPLOI.html (converti du MODE_EMPLOI.md de la release,
   pris dans le dépôt x32-gain-recall-workspace au tag GR_TAG) + version.txt ;
3. PyInstaller compile installer.py en UN fichier qui embarque build/stage.
Rien de personnel (calibration, réglage d'écran, journaux) n'est embarqué. Il faut PyInstaller et PySide6.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "XTouch-LV1"
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "build")
SHARED = ["LISEZMOI.md", "MODE_EMPLOI.html", "xtouch_couleurs.exemple.json"]
INSTALLER = "LV1_Suite_Install"
GR_REPO, GR_TAG, GR_EXE = "thaleosguest/x32-gain-recall", "v3.0.0", "XM32_Gain_Recall_LV1.exe"
GR_WORKSPACE = os.path.join(os.path.dirname(HERE), "x32-gain-recall-workspace")


def version():
    with open(os.path.join(HERE, "xtouch_lv1_display.py"), encoding="utf-8") as f:
        return re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)


def pyinstaller(args):
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--workpath", os.path.join(WORK, "work"), "--specpath", WORK] + args, cwd=HERE)
    if r.returncode:
        raise SystemExit("ÉCHEC de PyInstaller (code %d)." % r.returncode)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def gain_recall_release():
    """Exe de la release GR_TAG : en cache dans build/gainrecall/<tag>, sinon téléchargé ; empreinte SHA-256 comparée
    à celle que GitHub publie pour le fichier (champ digest de l'API)."""
    api = "https://api.github.com/repos/%s/releases/tags/%s" % (GR_REPO, GR_TAG)
    with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": "lv1-suite-build"}), timeout=20) as r:
        rel = json.loads(r.read())
    asset = next(a for a in rel["assets"] if a["name"] == GR_EXE)
    want = (asset.get("digest") or "").split(":")[-1]
    path = os.path.join(WORK, "gainrecall", GR_TAG, GR_EXE)
    if not (os.path.exists(path) and sha256(path) == want):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print("Téléchargement de %s %s (%.1f Mo)..." % (GR_EXE, GR_TAG, asset["size"] / 1e6))
        urllib.request.urlretrieve(asset["browser_download_url"], path + ".part")
        os.replace(path + ".part", path)
    got = sha256(path)
    if not want or got != want:
        os.remove(path)
        raise SystemExit("Empreinte de %s incorrecte (%s au lieu de %s) : fichier rejeté." % (GR_EXE, got, want))
    return path


# Mode d'emploi de Gain Recall : Markdown -> HTML (titres, paragraphes, listes, tableaux, citations, gras, italique,
# code, liens, images) ; assez pour MODE_EMPLOI.md, pas un convertisseur général.
def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"&lt;img ([^&]*)&gt;", lambda m: "<img %s>" % html.unescape(m.group(1)), s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(md, title):
    out, para, lst, table = [], [], None, []

    def flush():
        nonlocal lst
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para.clear()
        if lst:
            out.append("</%s>" % lst)
            lst = None
        if table:
            rows = [r for r in table if not re.match(r"^\|[\s:|-]+\|$", r)]
            out.append("<table>")
            for i, r in enumerate(rows):
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                tag = "th" if i == 0 else "td"
                out.append("<tr>%s</tr>" % "".join("<%s>%s</%s>" % (tag, inline(c), tag) for c in cells))
            out.append("</table>")
            table.clear()

    for line in md.split("\n"):
        line = line.rstrip()
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if not line:
            flush()
        elif line.startswith("|"):
            if para or lst:
                flush()
            table.append(line)
        elif m:
            flush()
            out.append("<h%d>%s</h%d>" % (len(m.group(1)), inline(m.group(2)), len(m.group(1))))
        elif line.startswith("> "):
            flush()
            out.append("<blockquote>%s</blockquote>" % inline(line[2:]))
        elif re.match(r"^\s*([-*]|\d+\.)\s+", line):
            if para or table:
                flush()
            kind = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            if lst != kind:
                if lst:
                    out.append("</%s>" % lst)
                out.append("<%s>" % kind)
                lst = kind
            out.append("<li>%s</li>" % inline(re.sub(r"^\s*([-*]|\d+\.)\s+", "", line)))
        elif re.match(r"^-{3,}$", line):
            flush()
            out.append("<hr>")
        else:
            if lst and line.startswith("  "):
                out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
            else:
                para.append(line)
    flush()
    css = ("body{margin:0;background:#f4f5f7;color:#1b1d20;font:15px/1.55 'Segoe UI',sans-serif}"
           "main{max-width:900px;margin:0 auto;padding:24px 16px 64px}"
           "h1{font-size:26px}h2{font-size:20px;margin-top:32px;border-bottom:2px solid #d9dde2;padding-bottom:6px}"
           "table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #d9dde2;padding:6px 10px;"
           "text-align:left;vertical-align:top}th{background:#eceff2}code{background:#fff;border:1px solid #d9dde2;"
           "border-radius:4px;padding:0 4px;font-family:Consolas,monospace}blockquote{border-left:4px solid #0f8fc4;"
           "margin:10px 0;padding:6px 12px;background:#fff}"
           "@media (prefers-color-scheme:dark){body{background:#111213;color:#e9edf0}table,blockquote,code{background:"
           "#1b1d20}th{background:#26292d}th,td,code{border-color:#33373c}a{color:#38c9ff}}")
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><title>%s</title><style>%s</style></head><body><main>\n%s\n'
            '</main></body></html>\n' % (html.escape(title), css, "\n".join(out)))


def stage_gain_recall(stage, exe, tag):
    os.makedirs(stage)
    shutil.copy2(exe, os.path.join(stage, GR_EXE))
    with open(os.path.join(stage, "version.txt"), "w", encoding="utf-8") as f:
        f.write(tag.lstrip("vV"))
    md = None
    if os.path.isdir(GR_WORKSPACE):                        # mode d'emploi du même tag que l'exe
        r = subprocess.run(["git", "show", "%s:MODE_EMPLOI.md" % tag], cwd=GR_WORKSPACE, capture_output=True)
        if r.returncode == 0:
            md = r.stdout.decode("utf-8")
            logo = subprocess.run(["git", "show", "%s:assets/logo.svg" % tag], cwd=GR_WORKSPACE, capture_output=True)
            if logo.returncode == 0:
                os.makedirs(os.path.join(stage, "assets"))
                with open(os.path.join(stage, "assets", "logo.svg"), "wb") as f:
                    f.write(logo.stdout)
    if md is None:
        print("  (mode d'emploi de Gain Recall introuvable : lien vers la page GitHub)")
        md = "# X32 Gain Recall\n\n[Mode d'emploi en ligne](https://github.com/%s/blob/%s/MODE_EMPLOI.md)\n" % (GR_REPO, tag)
    with open(os.path.join(stage, "MODE_EMPLOI.html"), "w", encoding="utf-8") as f:
        f.write(md_to_html(md, "X32 Gain Recall Mode d'emploi"))


def main():
    ap = argparse.ArgumentParser(description="Compilation de l'installeur LV1 Suite")
    ap.add_argument("--gain-recall", help="exe local de X32 Gain Recall (sinon la release %s)" % GR_TAG)
    ap.add_argument("--gain-recall-tag", default=GR_TAG, help="tag du mode d'emploi avec --gain-recall")
    ap.add_argument("--sans-gain-recall", action="store_true")
    a = ap.parse_args()
    ver = version()
    with open(os.path.join(HERE, "installer.py"), encoding="utf-8") as f:
        if 'VERSION = "%s"' % ver not in f.read():
            print("installer.py : VERSION différente de xtouch_lv1_display.py (%s)" % ver)
            return 1
    gr = None
    if not a.sans_gain_recall:
        gr = a.gain_recall or gain_recall_release()
        print("X32 Gain Recall : %s (%s)" % (gr, a.gain_recall_tag if a.gain_recall else GR_TAG))
    print("Compilation de %s v%s..." % (NAME, ver))
    out = os.path.join(WORK, "out")
    icon = os.path.join(HERE, "assets", "icon.ico")      # logo bleu (tools/make_icon.py)
    pyinstaller(["--console", "--uac-admin", "--icon", icon, "--name", NAME, "--distpath", out,
                 "--hidden-import", "xtouch_overlay_qt", os.path.join(HERE, "xtouch_lv1_display.py")])

    stage_root = os.path.join(WORK, "stage")
    shutil.rmtree(stage_root, ignore_errors=True)
    stage = os.path.join(stage_root, "xtouch")
    shutil.copytree(os.path.join(out, NAME), stage)
    os.makedirs(os.path.join(stage, "reaper"))
    for f in os.listdir(os.path.join(HERE, "reaper")):
        if f.endswith(".lua"):
            shutil.copy2(os.path.join(HERE, "reaper", f), os.path.join(stage, "reaper", f))
    for f in SHARED:
        shutil.copy2(os.path.join(HERE, f), os.path.join(stage, f))
    if gr:
        stage_gain_recall(os.path.join(stage_root, "gainrecall"), gr, a.gain_recall_tag if a.gain_recall else GR_TAG)

    pyinstaller(["--onefile", "--windowed", "--icon", icon, "--name", INSTALLER, "--distpath", DIST,
                 "--add-data", "%s%s." % (stage_root, os.pathsep),
                 "--add-data", "%s%sassets" % (icon, os.pathsep), os.path.join(HERE, "installer.py")])
    old = os.path.join(DIST, "XTouch_LV1_Install.exe")    # ancien nom (installeur XTouch-LV1 seul)
    if os.path.exists(old):
        os.remove(old)
    exe = os.path.join(DIST, INSTALLER + ".exe")
    print("OK : %s (%.0f Mo)" % (exe, os.path.getsize(exe) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
