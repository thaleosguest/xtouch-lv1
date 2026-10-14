#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prototype : affichage de la LV1 sur X-Touch + X-Touch Extender (USB).

Ce que ça fait :
  - suit la couche affichée dans la LV1 (Mixer 1 par défaut) ;
  - pour chacune des 16 tranches (8 sur la X-Touch, 8 sur l'Extender) :
      ligne du haut = nom du canal LV1, ligne du bas = position du fader en dB,
      couleur de l'écran = couleur du canal LV1 ramenée aux 7 couleurs de la X-Touch,
      vumètre = niveau post-fader envoyé par la LV1 (~23 fois par seconde).

Les faders motorisés se placent sur la position des faders LV1.

ÉTAPE 1 (écriture) : bouger un fader de la X-Touch règle le fader du canal dans la LV1
(/Set/Track/Out/Gain). Pendant que le doigt est sur le fader (+ 0,3 s après), les retours de la
LV1 pour ce fader sont ignorés, pour que le moteur ne se batte pas contre la main.
Les boutons et encodeurs ne font encore rien (ils sont seulement notés dans le journal).
Option --lecture-seule : rien n'est envoyé à la LV1.

Besoin de lv1_probe.py et xtouch_probe.py dans le même dossier. Python 3 standard.

AVANT : X-Touch et Extender en mode Mackie Control ; dans la LV1, retire le contrôleur
Mackie de System Inventory (sinon la LV1 garde les ports MIDI et ce script ne peut pas les ouvrir).

Usage :
    py xtouch_lv1_display.py
    py xtouch_lv1_display.py --mixer 2          # suit Mixer 2
    py xtouch_lv1_display.py --ext-droite       # Extender posée à DROITE de la X-Touch (gauche par défaut)
    py xtouch_lv1_display.py --main 3 --ext 5   # ports MIDI donnés par numéro
Arrêt : Ctrl+C (les écrans et vumètres sont remis à zéro).
"""
import argparse
import colorsys
import json
import os
import socket
import sys
import threading
import time
import queue
import unicodedata

import lv1_probe as L
import xtouch_probe as X

HERE = os.path.dirname(os.path.abspath(__file__))
COLOR_FILE = os.path.join(HERE, "xtouch_couleurs.json")

# Couleurs X-Touch (validées par xtouch_probe le 14/10/2026) : 0 vide, 1 rouge, 2 vert,
# 3 jaune, 4 bleu, 5 violet, 6 cyan, 7 blanc.
XT = {"vide": 0, "rouge": 1, "vert": 2, "jaune": 3, "bleu": 4, "violet": 5, "cyan": 6, "blanc": 7}

# Seuils dB -> niveau de vumètre Mackie 1..12 (niveau = nombre de seuils atteints).
# Choix provisoire : à ajuster à l'œil sur la X-Touch.
METER_STEPS = [-60.0, -50.0, -42.0, -36.0, -30.0, -24.0, -18.0, -12.0, -9.0, -6.0, -3.0, 0.0]

TICK = 0.05             # 20 rafraîchissements par seconde
METER_REFRESH = 0.25    # renvoi d'un niveau inchangé (le vumètre retombe tout seul sinon)


# ─── Conversions ──────────────────────────────────────────────────────────────

def ascii7(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return t.strip()


def short_name(name, group, ch):
    """« Channel 6 » -> « In 6 » (comme dans X/M32 Gain Recall), sinon le nom LV1 sur 7 caractères."""
    n = ascii7(name)
    if not n:
        n = default_label(group, ch)
    low = n.lower()
    if low.startswith("channel "):
        n = "In " + n[8:].strip()
    elif low.startswith("group "):
        n = "Grp " + n[6:].strip()
    return n[:7]


GROUP_TAG = {0: "In", 1: "Grp", 2: "Fx", 3: "LR", 4: "C", 5: "M", 6: "Mtx", 7: "Cue", 8: "TB", 12: "DCA", 25: "Mon"}


def default_label(group, ch):
    tag = GROUP_TAG.get(group, "g%d" % group)
    return tag if group in (3, 4, 5, 7, 8) else "%s %d" % (tag, ch + 1)


def fader_text(db):
    if db is None:
        return ""
    if db <= -120:
        return "  -inf"
    return ("%+.1f" % db).rjust(6)


def rgb_to_xtouch(rgb):
    """RVB 0..1 -> couleur X-Touch la plus proche, par la teinte."""
    if not rgb:
        return XT["blanc"]
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.25 or v < 0.15:
        return XT["blanc"]
    deg = h * 360.0
    if deg < 20 or deg >= 330:
        return XT["rouge"]
    if deg < 75:
        return XT["jaune"]
    if deg < 160:
        return XT["vert"]
    if deg < 200:
        return XT["cyan"]
    if deg < 260:
        return XT["bleu"]
    return XT["violet"]


# Courbe dB -> course du fader (0..1). Provisoire : haut = +10 dB, 0 dB aux 3/4.
FADER_CURVE = [(10.0, 1.0), (5.0, 0.875), (0.0, 0.75), (-5.0, 0.625), (-10.0, 0.5), (-20.0, 0.375),
               (-30.0, 0.25), (-40.0, 0.16), (-50.0, 0.09), (-60.0, 0.04), (-80.0, 0.0)]


def db_to_fader(db):
    """dB -> valeur 14 bits du fader motorisé (0..16383)."""
    if db is None or db <= FADER_CURVE[-1][0]:
        return 0
    if db >= FADER_CURVE[0][0]:
        return 16383
    for (d1, p1), (d2, p2) in zip(FADER_CURVE, FADER_CURVE[1:]):
        if d2 <= db <= d1:
            pos = p2 + (p1 - p2) * (db - d2) / (d1 - d2)
            return int(round(pos * 16383))
    return 0


CURVE_FILE = os.path.join(HERE, "xtouch_courbe_fader.json")
FADER_MIN_DB = -144.0   # « -inf » côté LV1 (plage -144..+10 d'après le module Companion)
INF_POS = 0.004         # course (0..1) en dessous de laquelle le fader vaut -inf (repère ∞ calibrable)


def load_fader_curve():
    """xtouch_courbe_fader.json : [[dB, course 0..1], ...] du haut vers le bas, plus éventuellement
    ["-inf", course] pour la position du repère ∞ (facultatif)."""
    global FADER_CURVE, INF_POS
    try:
        with open(CURVE_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        pts = []
        for d, p in raw:
            if isinstance(d, str) and d.strip().lower() in ("-inf", "inf", "bas"):
                INF_POS = max(0.004, float(p))
            else:
                pts.append((float(d), float(p)))
        pts.sort(key=lambda x: -x[0])
        if pts and pts[-1][0] > -80.0 and pts[-1][1] > INF_POS:
            pts.append((-80.0, INF_POS))   # sous le repère le plus bas : descente linéaire jusqu'au repère ∞
        if len(pts) >= 2:
            FADER_CURVE = pts
            print("  Courbe de fader personnalisée : %d points (xtouch_courbe_fader.json)" % len(pts))
    except (OSError, ValueError, TypeError):
        pass


def fader_to_db(value):
    """Valeur 14 bits du fader (0..16383) -> dB LV1, arrondi à 0,1 dB."""
    pos = max(0.0, min(1.0, value / 16383.0))
    if pos <= INF_POS:
        return FADER_MIN_DB
    top_db, top_pos = FADER_CURVE[0]
    if pos >= top_pos:
        return top_db
    for (d1, p1), (d2, p2) in zip(FADER_CURVE, FADER_CURVE[1:]):
        if p2 <= pos <= p1:
            db = d2 + (d1 - d2) * (pos - p2) / (p1 - p2) if p1 != p2 else d1
            return round(db, 1) + 0.0   # + 0.0 : évite « -0.0 »
    return FADER_MIN_DB


def db_to_level(db):
    if db is None:
        return 0
    return sum(1 for step in METER_STEPS if db >= step)


def load_color_overrides():
    """xtouch_couleurs.json : {"13": "cyan", "24": "jaune", ...} indexé par numéro de palette LV1."""
    try:
        with open(COLOR_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in raw.items():
        if str(k).startswith("_"):
            continue
        try:
            out[int(k)] = XT[v] if isinstance(v, str) else int(v)
        except (KeyError, ValueError, TypeError):
            print("  xtouch_couleurs.json : valeur ignorée %r -> %r" % (k, v))
    return out


# ─── État de la LV1 ───────────────────────────────────────────────────────────

class LV1State:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.tracks = {}          # (g, ch) -> {"name", "rgb", "pal", "fader"}
        self.meters = {}          # (g, ch, sub) -> dB
        # Couches reçues, par (vue, custom) : vue 0 = Mixer 1, 1 = Mixer 2 ; custom 0 = usine, 1 = perso.
        # Hypothèse tirée du journal du 14/10 : le 1er nombre de /Notify/Layers est la vue.
        self.last_set = {}        # vue -> dernier jeu de couches reçu [(nom, [(g, ch) | None, ...]), ...]
        self.last_flag = {}       # vue -> 2e nombre de ce paquet (1 = custom d'après le module Companion)
        self.current = {}         # vue -> index de couche (/Notify/CurrentLayer)
        self.custom_on = {}       # vue -> bouton Custom allumé ? (/Notify/CustomButton, hypothèse)
        self.spill_on = {}        # vue -> bouton Spill allumé ? (/Notify/SpillButton, hypothèse)
        self.version = ""
        self.held_tracks = set()  # (g, ch) dont le fader X-Touch est sous le doigt : retours LV1 ignorés
        # (g, ch) -> (valeurs « périmées » en dB arrondi, instant de fin) : après le relâchement, un retour
        # LV1 égal à l'ancienne valeur ou à une valeur intermédiaire du geste est ignoré (retour tardif).
        self.stale = {}

    def track(self, g, ch):
        return self.tracks.setdefault((g, ch), {"name": None, "rgb": None, "pal": None, "fader": None,
                                                "mute": None, "solo": None})

    def layer_set(self, page):
        """Jeu de couches affiché sur cette vue.

        Constat du journal du 14/10/2026 (LV1 17.6) : à chaque clic de couche, la LV1 envoie
        d'abord /Notify/Layers (le jeu affiché : usine, custom ou autre) puis /Notify/CurrentLayer.
        Le 2e nombre de /Notify/Layers ne dit PAS toujours « custom », et /Notify/CustomButton ne
        change pas quand on allume Custom. On suit donc simplement le dernier jeu reçu pour la vue."""
        if page in self.last_set:
            return self.last_set[page], "custom" if self.last_flag.get(page) else "usine"
        if (1 - page) in self.last_set:
            return self.last_set[1 - page], "usine"
        return None, None

    def layer_entries(self, mixer_page):
        """Les 16 tranches de la couche affichée, ou (None, None) si inconnue."""
        idx = self.current.get(mixer_page)
        layers, kind = self.layer_set(mixer_page)
        if idx is None or not layers:
            return None, None
        if 0 <= idx < len(layers):
            name, entries = layers[idx]
            if not any(entries):
                name += " (vide)"
            return name, entries
        return None, None


def parse_layers(args):
    """/Notify/Layers : page, custom(0|1), nb, puis par couche : nom, n, (groupe, canal) x n."""
    if len(args) < 3 or any(a[0] != "i" for a in args[:3]):
        return None, None, []
    page = args[0][1]
    is_custom = args[1][1] == 1
    count = args[2][1]
    layers = []
    i = 3
    for _ in range(max(0, min(count, 32))):
        if i + 1 >= len(args) or args[i][0] != "s" or args[i + 1][0] != "i":
            break
        name, n = args[i][1], args[i + 1][1]
        i += 2
        entries = []
        for _ in range(max(0, n)):
            if i + 1 >= len(args):
                break
            g, c = args[i][1], args[i + 1][1]
            i += 2
            entries.append(None if (g == -1 and c == -1) else (g, c))
        layers.append((name, entries))
    return page, is_custom, layers


JOURNAL_SKIP = {"/Notify/Meters", "/ping", "/Notify/NetworkCongestion", "/Notify/TempoBlink"}


class Journal:
    """Journal complet (arguments non tronqués) pour décoder couches, Custom, Spill, 80 canaux."""
    def __init__(self, path):
        self.path = path
        self.t0 = time.time()
        self.f = open(path, "w", encoding="utf-8") if path else None
        self.lock = threading.Lock()

    def write(self, address, args):
        if not self.f or address in JOURNAL_SKIP:
            return
        with self.lock:
            self.f.write("%.3f %s %s\n" % (time.time() - self.t0, address, L.short_args(args, 100000)))
            self.f.flush()

    def mark(self, text):
        if self.f:
            with self.lock:
                self.f.write("%.3f ===== %s\n" % (time.time() - self.t0, text))
                self.f.flush()


JOURNAL = Journal(None)


def handle(state, address, args):
    JOURNAL.write(address, args)
    if address == "/Notify/Meters":
        with state.lock:
            for i in range(1, len(args) - 3, 4):
                g, c, s, d = args[i], args[i + 1], args[i + 2], args[i + 3]
                if g[0] == "i" and c[0] == "i" and s[0] == "i" and d[0] == "f":
                    state.meters[(g[1], c[1], s[1])] = d[1]
        return
    with state.lock:
        if address == "/Notify/TrackColor" and len(args) >= 6:
            t = state.track(args[0][1], args[1][1])
            t["pal"] = args[2][1] if args[2][0] == "i" else None
            t["rgb"] = tuple(a[1] for a in args[3:6])
        elif address in ("/Notify/Track/Name", "/Notify/TrackName") and len(args) >= 3 and args[2][0] == "s":
            state.track(args[0][1], args[1][1])["name"] = args[2][1]
        elif address == "/Notify/Track/Out/Mute" and len(args) >= 3 and args[2][0] == "i":
            # ,iiiT [groupe, canal, muet 0|1, T] ; groupe 13 = groupes de mute (module Companion)
            if args[0][1] != 13:
                state.track(args[0][1], args[1][1])["mute"] = args[2][1] != 0
        elif address == "/Notify/Solo" and len(args) >= 3 and args[2][0] == "i":
            state.track(args[0][1], args[1][1])["solo"] = args[2][1] != 0
        elif address == "/Notify/Track/Out/Gain" and len(args) >= 3 and args[2][0] in "fdi":
            key = (args[0][1], args[1][1])
            val = float(args[2][1])
            st = state.stale.get(key)
            if key in state.held_tracks:
                JOURNAL.mark("retour LV1 ignoré %s %s (fader tenu)" % (key, val))
            elif st and time.time() < st[1] and round(val, 1) in st[0]:
                JOURNAL.mark("retour LV1 ignoré %s %s (valeur périmée)" % (key, val))
            else:
                state.track(*key)["fader"] = val
        elif address == "/Channels" and args and args[0][0] == "i":
            count = args[0][1]
            for k in range(max(0, min(count, 256))):
                base = 1 + k * 19
                if base + 3 >= len(args):
                    break
                n, g, c, f = args[base], args[base + 1], args[base + 2], args[base + 3]
                if n[0] == "s" and g[0] == "i" and c[0] == "i":
                    t = state.track(g[1], c[1])
                    t["name"] = n[1]
                    # Hypothèse (non vérifiée) : 1er double = fader en dB (-144 = -inf).
                    if f[0] == "d" and t["fader"] is None:
                        t["fader"] = f[1]
        elif address == "/Notify/Layers":
            page, is_custom, layers = parse_layers(args)
            if layers:
                state.last_set[page] = layers
                state.last_flag[page] = is_custom
        elif address == "/Notify/CustomButton" and len(args) >= 2 and args[1][0] == "i":
            state.custom_on[args[0][1]] = args[1][1] != 0
        elif address == "/Notify/SpillButton" and len(args) >= 2 and args[1][0] == "i":
            state.spill_on[args[0][1]] = args[1][1] != 0
        elif address == "/Notify/CurrentLayer" and len(args) >= 2:
            state.current[args[0][1]] = args[1][1]
        elif address == "/Notify/ServiceVersion" and args and args[0][0] == "s":
            state.version = args[0][1]


# ─── Lien réseau avec la LV1 (lecture seule, reconnexion automatique) ────────

class LV1Link(threading.Thread):
    def __init__(self, state, host=None, port=None, name="XTouch-Display"):
        super().__init__(daemon=True)
        self.state = state
        self.host, self.port = host, port
        self.name_ = name
        self.stop_flag = False
        self.sock = None
        self.send_lock = threading.Lock()

    def send(self, address, args):
        """Envoie un message à la LV1 (ignoré si pas connectée)."""
        with self.send_lock:
            if self.sock is None:
                return False
            try:
                self.sock.sendall(L.frame(address, args))
                return True
            except OSError:
                return False

    def run(self):
        while not self.stop_flag:
            try:
                self.session()
            except OSError as e:
                print("  LV1 : %s" % e)
            with self.state.lock:
                self.state.connected = False
            if not self.stop_flag:
                time.sleep(3)

    def locate(self):
        if self.host and self.port:
            return [self.host], self.port
        found = L.discover(timeout=6)
        if self.host:
            found = [e for e in found if self.host in e["ipv4"]] or found
        if not found:
            raise OSError("LV1 introuvable (nouvel essai dans 3 s)")
        e = found[0]
        addrs = ([self.host] if self.host else [])
        if any(ip in L.local_ipv4s() for ip in e["ipv4"]):
            addrs.append("127.0.0.1")
        addrs += e["ipv4"] + [e["source"]]
        return list(dict.fromkeys(addrs)), self.port or e["port"]

    def session(self):
        addrs, port = self.locate()
        sock, ip = L.connect_any(addrs, port)
        ack = threading.Event()
        buf = b""
        try:
            sock.sendall(L.frame("/handshake", [("i", 1), ("i", -1), ("i", 1)]) +
                         L.frame("/device_name", [("s", self.name_), ("s", "XTOUCH-LV1-DISPLAY-0001")]))
            asked = False
            t_ack = time.time() + 3
            while not self.stop_flag:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    chunk = None
                if chunk == b"":
                    raise OSError("la LV1 a fermé la connexion")
                if chunk:
                    buf += chunk
                    packets, buf = L.split_frames(buf)
                    for p in packets:
                        try:
                            address, args = L.osc_decode(p)
                        except Exception:
                            continue
                        if address == "/ping":
                            with self.send_lock:
                                sock.sendall(L.frame("/pong", args))
                        elif address == "/handshake" and args[:1] == [("i", 1)]:
                            ack.set()
                        else:
                            handle(self.state, address, args)
                if ack.is_set() and not asked:
                    asked = True
                    with self.send_lock:
                        self.sock = sock
                    with self.state.lock:
                        self.state.connected = True
                    print("  LV1 connectée (%s:%d)" % (ip, port))
                    sock.sendall(L.frame("/Get/Aux/Tracks") + L.frame("/Get/Layers", [("i", 0), ("i", 0)]))
                if not ack.is_set() and time.time() > t_ack:
                    raise OSError("pas de réponse à la poignée de main")
        finally:
            with self.send_lock:
                self.sock = None
            try:
                sock.close()
            except OSError:
                pass


# ─── Surface X-Touch ──────────────────────────────────────────────────────────

class Surface:
    def __init__(self, midi, units):
        """units = liste ordonnée de (libellé, id sysex, handle) ; 8 tranches par unité."""
        self.midi = midi
        self.units = units
        self.sent_lcd = {}     # (unité, ligne) -> texte de 56 caractères
        self.sent_color = {}   # unité -> tuple de 8 couleurs
        self.sent_meter = {}   # (unité, tranche) -> (niveau, instant)
        self.sent_fader = {}   # (unité, tranche) -> valeur 14 bits
        self.motor = {}        # tranche -> (valeur, instant) de la dernière commande moteur
        self.sent_led = {}     # (unité, note) -> 0 | 127
        # Le master est sur la X-Touch (canal MIDI 8) ; l'Extender n'en a pas.
        self.master_unit = next((i for i, un in enumerate(units) if un[0] == "X-Touch"), None)

    def addr(self, strip):
        """Tranche -> (unité, canal MIDI du fader)."""
        if strip == MASTER:
            return (self.master_unit, 8) if self.master_unit is not None else (None, None)
        return strip // 8, strip % 8

    def strip_of(self, unit, chan):
        """(unité, canal MIDI du fader) -> tranche, ou None."""
        if chan == 8:
            return MASTER if unit == self.master_unit else None
        return 8 * unit + chan if chan < 8 else None

    def note_position(self, strip, value):
        """La main a mis le fader à cette valeur : on la renvoie aussitôt à la X-Touch (écho Mackie).

        Sans cet écho, la X-Touch garde la dernière position envoyée par l'ordinateur et, au
        relâchement, son moteur y ramène le fader (constaté le 14/10 : retour à -14,6 dB)."""
        u, s = self.addr(strip)
        if u is None:
            return
        if u < len(self.units):
            h = self.units[u][2]
            self.midi.short(h, 0xE0 | s, value & 0x7F, (value >> 7) & 0x7F)
        self.sent_fader[(u, s)] = value

    def set_led(self, unit, note, on):
        """LED d'un bouton Mackie : note on, vélocité 127 = allumée, 0 = éteinte."""
        v = 127 if on else 0
        if self.sent_led.get((unit, note)) != v and unit < len(self.units):
            self.midi.short(self.units[unit][2], 0x90, note, v)
            self.sent_led[(unit, note)] = v

    def push_leds(self, mutes, solos):
        for i, (m, so) in enumerate(zip(mutes, solos)):
            u, s = i // 8, i % 8
            self.set_led(u, NOTE_MUTE + s, bool(m))
            self.set_led(u, NOTE_SOLO + s, bool(so))
            self.set_led(u, NOTE_REC + s, False)
            self.set_led(u, NOTE_SELECT + s, False)

    @property
    def strips(self):
        return 8 * len(self.units)

    def push(self, labels_top, labels_bot, colors, levels, faders, now, held=(), master_fv=None):
        if master_fv is not None and self.master_unit is not None and MASTER not in held:
            key = (self.master_unit, 8)
            prev_f = self.sent_fader.get(key)
            if prev_f is None or abs(prev_f - master_fv) > FADER_TOL or (master_fv == 0) != (prev_f == 0):
                h = self.units[self.master_unit][2]
                self.midi.short(h, 0xE8, master_fv & 0x7F, (master_fv >> 7) & 0x7F)
                self.sent_fader[key] = master_fv
                self.motor[MASTER] = (master_fv, now)
                JOURNAL.mark("moteur master -> %d (%s dB)" % (master_fv, fader_to_db(master_fv)))
        for u, (_, dev, h) in enumerate(self.units):
            sl = slice(8 * u, 8 * u + 8)
            for row, labels in ((0, labels_top[sl]), (1, labels_bot[sl])):
                text = "".join(x[:7].ljust(7) for x in labels)
                if self.sent_lcd.get((u, row)) != text:
                    self.midi.long(h, X.msg_lcd(dev, 0 if row == 0 else 56, text))
                    self.sent_lcd[(u, row)] = text
            cols = tuple(colors[sl])
            if self.sent_color.get(u) != cols:
                self.midi.long(h, X.msg_colors(dev, cols))
                self.sent_color[u] = cols
            for s in range(8):
                fv = faders[8 * u + s]
                prev_f = self.sent_fader.get((u, s))
                if (8 * u + s) not in held and (prev_f is None or abs(prev_f - fv) > FADER_TOL
                                                  or (fv == 0) != (prev_f == 0)):
                    self.midi.short(h, 0xE0 | s, fv & 0x7F, (fv >> 7) & 0x7F)
                    self.sent_fader[(u, s)] = fv
                    self.motor[8 * u + s] = (fv, now)
                    JOURNAL.mark("moteur tranche %d -> %d (%s dB)" % (8 * u + s + 1, fv, fader_to_db(fv)))
                lvl = levels[8 * u + s]
                prev = self.sent_meter.get((u, s))
                if prev is None or prev[0] != lvl or (lvl > 0 and now - prev[1] >= METER_REFRESH):
                    st, d1 = X.msg_meter(s, lvl)
                    self.midi.short(h, st, d1)
                    self.sent_meter[(u, s)] = (lvl, now)

    def clear(self):
        for u, (_, dev, h) in enumerate(self.units):
            try:
                for s in range(8):
                    st, d1 = X.msg_meter(s, 0)
                    self.midi.short(h, st, d1)
                    self.midi.short(h, 0xE0 | s, 0, 0)
                    for base in (NOTE_REC, NOTE_SOLO, NOTE_MUTE, NOTE_SELECT):
                        self.midi.short(h, 0x90, base + s, 0)
                if u == self.master_unit:
                    self.midi.short(h, 0xE8, 0, 0)
                self.midi.long(h, X.msg_colors(dev, [7] * 8))
                self.midi.long(h, X.msg_lcd(dev, 0, " " * 112))
            except OSError:
                pass


# ─── Entrée MIDI (faders, toucher, boutons) ───────────────────────────────────

class WinMidiIn:
    """Entrée MIDI Windows (winmm). Les messages arrivent dans une file : (unité, status, d1, d2, instant)."""
    MIM_DATA = 0x3C3
    CALLBACK_FUNCTION = 0x00030000

    def __init__(self, events):
        import ctypes
        from ctypes import wintypes as wt
        self.ct = ctypes
        self.w = ctypes.WinDLL("winmm")
        self.events = events
        self.handles = []
        self._keep = []

        class MIDIINCAPSW(ctypes.Structure):
            _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                        ("szPname", wt.WCHAR * 32), ("dwSupport", wt.DWORD)]
        self.CAPS = MIDIINCAPSW
        self.PROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, wt.UINT, ctypes.c_size_t,
                                       ctypes.c_size_t, ctypes.c_size_t)
        w = self.w
        w.midiInGetNumDevs.restype = wt.UINT
        w.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIINCAPSW), wt.UINT]
        w.midiInOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), wt.UINT, ctypes.c_void_p,
                                 ctypes.c_size_t, wt.DWORD]
        w.midiInStart.argtypes = [ctypes.c_void_p]
        w.midiInStop.argtypes = [ctypes.c_void_p]
        w.midiInClose.argtypes = [ctypes.c_void_p]

    def list(self):
        out = []
        for i in range(self.w.midiInGetNumDevs()):
            caps = self.CAPS()
            if self.w.midiInGetDevCapsW(i, self.ct.byref(caps), self.ct.sizeof(caps)) == 0:
                out.append((i, caps.szPname))
        return out

    def open(self, index, unit):
        def cb(hmi, msg, inst, p1, p2, unit=unit):
            if msg == self.MIM_DATA:
                self.events.put((unit, p1 & 0xFF, (p1 >> 8) & 0x7F, (p1 >> 16) & 0x7F, time.time()))
        proc = self.PROC(cb)
        self._keep.append(proc)
        h = self.ct.c_void_p()
        r = self.w.midiInOpen(self.ct.byref(h), index, self.ct.cast(proc, self.ct.c_void_p), 0,
                              self.CALLBACK_FUNCTION)
        if r != 0:
            raise OSError("entrée MIDI %d : erreur %d%s" % (index, r, " (déjà ouverte ?)" if r == 4 else ""))
        self.w.midiInStart(h)
        self.handles.append(h)
        return h

    def close_all(self):
        for h in self.handles:
            try:
                self.w.midiInStop(h)
                self.w.midiInClose(h)
            except OSError:
                pass


EVENTS = queue.Queue()  # messages MIDI reçus (global : les tests peuvent en injecter)
FADER_TOL = 48          # écart (sur 16383) en dessous duquel on ne bouge pas le moteur
HOLD_AFTER = 0.3        # s pendant lesquelles un fader lâché reste « tenu » (retours LV1 ignorés)
STALE_FOR = 2.0         # s après le relâchement pendant lesquelles un retour « périmé » est ignoré
SEND_EVERY = 0.02       # envoi max d'une valeur par fader toutes les 20 ms
TOUCH_NOTES = range(0x68, 0x71)   # notes de toucher : 0x68-0x6F faders 1-8, 0x70 master (norme Mackie)
MASTER = 16                       # numéro interne du fader master (9e fader de la X-Touch)


# Boutons de tranche, notes Mackie (à confirmer sur la X-Touch) : Rec 0x00-07, Solo 0x08-0F,
# Mute 0x10-17, Select 0x18-1F. Appui = vélocité 127, relâchement = 0.
NOTE_REC, NOTE_SOLO, NOTE_MUTE, NOTE_SELECT = 0x00, 0x08, 0x10, 0x18


class ButtonControl:
    """Mute / Solo -> LV1. Rec et Select : pas encore de fonction (notés dans le journal)."""

    def __init__(self, state, link, write=True):
        self.state, self.link, self.write = state, link, write
        self.warned = set()

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        if (status & 0xF0) != 0x90 or d1 > 0x1F:
            return False
        if d2 == 0:
            return True                       # relâchement : rien à faire
        base, s = d1 & 0x18, d1 & 0x07
        strip = 8 * unit + s
        kind = {NOTE_REC: "Rec", NOTE_SOLO: "Solo", NOTE_MUTE: "Mute", NOTE_SELECT: "Select"}[base]
        e = entries[strip] if strip < len(entries) else None
        JOURNAL.mark("XT bouton %s tranche %d (piste %s)" % (kind, strip + 1, e))
        if e is None:
            return True
        g, ch = e
        if kind in ("Rec", "Select"):
            if kind not in self.warned:
                print("  Bouton %s : pas encore de fonction (noté dans le journal)." % kind)
                self.warned.add(kind)
            return True
        field = "mute" if kind == "Mute" else "solo"
        with self.state.lock:
            t_ = self.state.track(g, ch)
            new = not bool(t_.get(field))
            t_[field] = new                   # mise à jour locale immédiate (LED)
        if self.write:
            if kind == "Mute":
                self.link.send("/Set/Track/Out/Mute", [("i", g), ("i", ch), ("T" if new else "F", new)])
            else:
                self.link.send("/Set/Solo", [("i", g), ("i", ch), ("i", 1 if new else 0)])
            JOURNAL.mark("-> LV1 %s %d %d %s" % (kind, g, ch, new))
        return True


def label_of(strip):
    return "master" if strip == MASTER else str(strip + 1)


class FaderControl:
    """Faders X-Touch -> LV1, avec gestion du toucher."""

    def __init__(self, state, link, write=True):
        self.state, self.link, self.write = state, link, write
        self.touched = {}      # tranche -> bool
        self.hold_until = {}   # tranche -> instant
        self.pending = {}      # tranche -> (g, ch, dB, valeur 14 bits)
        self.last_sent = {}    # tranche -> instant du dernier envoi
        self.seen_touch = False
        self.gesture = {}      # (g, ch) -> valeurs du geste en cours (ancienne valeur + valeurs envoyées)

    def held(self, now):
        return {s for s in set(self.touched) | set(self.hold_until)
                if self.touched.get(s) or now < self.hold_until.get(s, 0)}

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        kind = status & 0xF0
        chan = status & 0x0F
        if kind == 0xE0 and surface.strip_of(unit, chan) is not None:   # fader bougé (pitch bend)
            strip = surface.strip_of(unit, chan)
            value = d1 | (d2 << 7)
            # Garde-fou 1 : si la X-Touch envoie le toucher, un fader non touché ne compte pas
            # (c'est le moteur qui bouge, pas la main).
            if self.seen_touch and not self.touched.get(strip):
                JOURNAL.mark("XT fader %s = %d ignoré (pas touché)" % (label_of(strip), value))
                return True
            # Garde-fou 2 : valeur proche d'une commande moteur récente (venue de la LV1) = écho du moteur.
            mv = surface.motor.get(strip)
            if not self.touched.get(strip) and mv and abs(mv[0] - value) <= 160 and t - mv[1] < 1.5:
                JOURNAL.mark("XT fader %s = %d ignoré (écho moteur)" % (label_of(strip), value))
                return True
            # Valeur identique à la dernière connue pour ce fader : rien de nouveau (évite toute boucle d'écho).
            if surface.sent_fader.get(surface.addr(strip)) == value:
                self.hold_until[strip] = t + HOLD_AFTER
                return True
            self.hold_until[strip] = t + HOLD_AFTER
            surface.note_position(strip, value)
            e = entries[strip] if strip < len(entries) else None
            if e is not None:
                key = (e[0], e[1])
                if key not in self.gesture:
                    with self.state.lock:
                        old = self.state.tracks.get(key, {}).get("fader")
                    self.gesture[key] = {round(old, 1)} if old is not None else set()
                self.pending[strip] = (e[0], e[1], fader_to_db(value), value)
            JOURNAL.mark("XT fader %s = %d (%s dB)" % (label_of(strip), value, fader_to_db(value)))
            return True
        if kind in (0x90, 0x80) and d1 in TOUCH_NOTES:      # toucher / relâcher
            strip = MASTER if d1 == 0x70 else 8 * unit + (d1 - 0x68)
            if d1 == 0x70 and unit != surface.master_unit:
                return False
            down = kind == 0x90 and d2 > 0
            if down and not self.seen_touch:
                self.seen_touch = True
                print("  Toucher des faders détecté (notes Mackie 0x68-0x6F).")
            self.touched[strip] = down
            JOURNAL.mark("XT toucher fader %s : %s" % (label_of(strip), "posé" if down else "lâché"))
            if not down:
                self.hold_until[strip] = t + HOLD_AFTER
            return True
        return False

    def flush(self, now):
        """Envoie à la LV1 les positions en attente (limité à une toutes les 20 ms par fader)."""
        held_now = self.held(now)
        for strip, (g, ch, db, value) in list(self.pending.items()):
            if now - self.last_sent.get(strip, 0) < SEND_EVERY:
                continue
            with self.state.lock:
                t = self.state.track(g, ch)
                changed = t.get("fader") != db
                t["fader"] = db            # mise à jour locale : la LV1 ne nous renvoie pas nos propres envois
            if changed:
                self.gesture.setdefault((g, ch), set()).add(round(db, 1))
            if changed and self.write:
                self.link.send("/Set/Track/Out/Gain", [("i", g), ("i", ch), ("d", float(db))])
                JOURNAL.mark("-> LV1 /Set/Track/Out/Gain %d %d %s" % (g, ch, db))
            self.last_sent[strip] = now
            if strip not in held_now:
                del self.pending[strip]
                vals = self.gesture.pop((g, ch), set()) - {round(db, 1)}
                with self.state.lock:
                    self.state.stale[(g, ch)] = (vals, now + STALE_FOR)
        with self.state.lock:
            self.state.held_tracks = {self.pending[s][:2] for s in self.pending}
        return held_now


def build_frame(state, mixer_page, n_strips, overrides):
    """Calcule ce que chaque tranche doit afficher."""
    with state.lock:
        if not state.connected:
            top = ["LV1 ?"] + [""] * (n_strips - 1)
            bot = ["attente"] + [""] * (n_strips - 1)
            state.last_leds = ([False] * n_strips, [False] * n_strips)
            return top, bot, [XT["blanc"]] + [XT["vide"]] * (n_strips - 1), [0] * n_strips, [0] * n_strips, None, [None] * n_strips
        layer_name, entries = state.layer_entries(mixer_page)
        if entries is None:
            # Couche inconnue (pas encore reçue) : 1re couche d'usine, sinon In 1-16.
            layers, _ = state.layer_set(mixer_page)
            if layers:
                layer_name, entries = layers[0]
                layer_name += " (par défaut)"
            else:
                layer_name, entries = "In 1-16 (par défaut)", [(0, i) for i in range(16)]
        entries = list(entries or [])[:n_strips]
        entries += [None] * (n_strips - len(entries))
        top, bot, cols, lvls, fads = [], [], [], [], []
        mutes, solos = [], []
        for e in entries:
            if e is None:
                top.append(""); bot.append(""); cols.append(XT["vide"]); lvls.append(0); fads.append(0)
                mutes.append(False); solos.append(False)
                continue
            g, c = e
            t = state.tracks.get((g, c), {})
            top.append(short_name(t.get("name"), g, c))
            bot.append(fader_text(t.get("fader")))
            fads.append(db_to_fader(t.get("fader")))
            mutes.append(bool(t.get("mute")))
            solos.append(bool(t.get("solo")))
            pal = t.get("pal")
            cols.append(overrides.get(pal, rgb_to_xtouch(t.get("rgb"))) if pal is not None
                        else rgb_to_xtouch(t.get("rgb")))
            left = state.meters.get((g, c, 0))
            right = state.meters.get((g, c, 1))
            vals = [v for v in (left, right) if v is not None]
            lvls.append(db_to_level(max(vals)) if vals else 0)
        state.last_leds = (mutes, solos)
        return top, bot, cols, lvls, fads, layer_name, entries


def main():
    ap = argparse.ArgumentParser(description="LV1 sur X-Touch + Extender : affichage + faders (étape 1).")
    ap.add_argument("--mixer", type=int, choices=[1, 2], default=1, help="vue suivie : Mixer 1 ou 2 (1)")
    ap.add_argument("--main", type=int, help="numéro du port MIDI de la X-Touch")
    ap.add_argument("--ext", type=int, help="numéro du port MIDI de l'Extender")
    ap.add_argument("--ext-droite", action="store_true",
                    help="Extender à droite de la X-Touch (par défaut : à gauche, elle affiche les tranches 1-8)")
    ap.add_argument("--ext-left", action="store_true", help=argparse.SUPPRESS)   # ancien nom, sans effet
    ap.add_argument("--host", help="IP de la LV1 (sinon découverte automatique)")
    ap.add_argument("--port", type=int, help="port TCP de la LV1")
    ap.add_argument("--dry-run", action="store_true", help="n'ouvre pas de port MIDI, affiche les octets")
    ap.add_argument("--seconds", type=float, default=0, help="arrêt automatique après N s (test)")
    ap.add_argument("--no-journal", action="store_true", help="ne pas écrire le journal des messages LV1")
    ap.add_argument("--lecture-seule", action="store_true", help="n'envoie rien à la LV1 (faders sans effet)")
    ap.add_argument("--master", default="3:0",
                    help="piste LV1 du fader master, groupe:canal (3:0 = LR, défaut ; 'aucun' pour désactiver)")
    a = ap.parse_args()

    global JOURNAL
    if not a.no_journal:
        jpath = os.path.join(HERE, "xtouch_journal_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        JOURNAL = Journal(jpath)
        print("  Journal des messages LV1 : %s" % jpath)

    if a.dry_run:
        midi = X.DryOut()
    elif sys.platform != "win32":
        print("Windows uniquement (ou --dry-run).")
        return 2
    else:
        midi = X.WinMidiOut()

    ports = midi.list()
    main_idx, ext_idx = X.pick_ports(ports, a.main, a.ext)
    units = []
    for label, idx, dev in (("X-Touch", main_idx, X.ID_MAIN), ("Extender", ext_idx, X.ID_EXT)):
        if idx is None:
            print("  %s : port introuvable, ignorée." % label)
            continue
        try:
            units.append((label, dev, midi.open(idx)))
            print("  %s : port %d « %s »" % (label, idx, dict(ports).get(idx, "?")))
        except OSError as e:
            print("  %s : %s" % (label, e))
    if not units:
        print("Aucune X-Touch utilisable. Liste des ports : py xtouch_probe.py --list")
        return 3
    # Par défaut l'Extender est à GAUCHE (installation de Joseph) : elle porte les tranches 1-8.
    if not a.ext_droite and len(units) == 2:
        units.reverse()

    # Entrées MIDI : même ordre que les sorties (unité 0 = tranches 1-8).
    events = EVENTS
    midi_in = None
    if not a.dry_run:
        midi_in = WinMidiIn(events)
        in_ports = midi_in.list()
        in_main, in_ext = X.pick_ports(in_ports, None, None)
        by_label = {"X-Touch": in_main, "Extender": in_ext}
        for u, (label, _, _) in enumerate(units):
            idx = by_label.get(label)
            if idx is None:
                print("  %s : entrée MIDI introuvable (faders sans effet)." % label)
                continue
            try:
                midi_in.open(idx, u)
                print("  %s : entrée %d « %s »" % (label, idx, dict(in_ports).get(idx, "?")))
            except OSError as e:
                print("  %s : %s" % (label, e))
    load_fader_curve()

    overrides = load_color_overrides()
    if overrides:
        print("  Couleurs personnalisées : %d entrées (xtouch_couleurs.json)" % len(overrides))

    state = LV1State()
    link = LV1Link(state, a.host, a.port)
    link.start()
    surface = Surface(midi, units)
    faders = FaderControl(state, link, write=not a.lecture_seule)
    buttons = ButtonControl(state, link, write=not a.lecture_seule)
    if a.lecture_seule:
        print("  Mode lecture seule : rien n'est envoyé à la LV1.")
    print("Recherche de la LV1… (Ctrl+C pour arrêter)")
    entries = [None] * surface.strips
    master_target = None
    if a.master.lower() not in ("aucun", "none", "off"):
        try:
            g_, c_ = (int(x) for x in a.master.split(":"))
            master_target = (g_, c_)
        except ValueError:
            print("  --master %r invalide (attendu groupe:canal, ex. 3:0) : master désactivé." % a.master)
    if master_target and surface.master_unit is not None:
        print("  Fader master -> %s" % default_label(*master_target))
    last_layer = object()
    t_end = time.time() + a.seconds if a.seconds else None
    try:
        while not (t_end and time.time() > t_end):
            now = time.time()
            while True:
                try:
                    unit, st, d1, d2, t = events.get_nowait()
                except queue.Empty:
                    break
                if not (faders.on_midi(unit, st, d1, d2, t, entries, surface)
                        or buttons.on_midi(unit, st, d1, d2, t, entries, surface)):
                    JOURNAL.mark("MIDI unité %d : %02X %02X %02X" % (unit, st, d1, d2))
            held = faders.flush(now)
            top, bot, cols, lvls, fads, layer_name, entries = build_frame(state, a.mixer - 1, surface.strips, overrides)
            entries = list(entries) + [None] * (MASTER - len(entries)) + [master_target]
            master_fv = None
            if master_target:
                with state.lock:
                    connected = state.connected
                    mdb = state.tracks.get(master_target, {}).get("fader")
                master_fv = db_to_fader(mdb) if connected and mdb is not None else None
            if layer_name != last_layer:
                if layer_name:
                    print("  Couche affichée : %s" % layer_name)
                    JOURNAL.mark("affiché : %s" % layer_name)
                last_layer = layer_name
            surface.push(top, bot, cols, lvls, fads, now, held, master_fv)
            surface.push_leds(*state.last_leds)
            time.sleep(0.01 if faders.pending else TICK)
    except KeyboardInterrupt:
        pass
    finally:
        link.stop_flag = True
        if midi_in:
            midi_in.close_all()
        surface.clear()
        for _, _, h in units:
            midi.close(h)
        print("\nArrêté, écrans remis à zéro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
