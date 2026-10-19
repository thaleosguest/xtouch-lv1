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
import json
import os
import socket
import sys
import threading
import time
import queue

import lv1_probe as L
import osc
import xtouch_probe as X
from surface.notes import (XT, TOUCH_NOTES, MASTER, NOTE_REC, NOTE_SOLO, NOTE_MUTE, NOTE_SELECT,
                           NOTE_BANK_LEFT, NOTE_BANK_RIGHT, NOTE_CHANNEL_LEFT, NOTE_CHANNEL_RIGHT, CC_JOG,
                           NOTE_FLIP, NOTE_GLOBAL_VIEW, NOTE_INPUTS, NOTE_BUSES, NOTE_USER, NOTE_GROUP,
                           NOTE_SMPTE, NOTE_LED_SMPTE, NOTE_SOLO_ALL, NOTE_TRACK, NOTE_PAN, NOTE_VPOT_PUSH,
                           CC_VPOT, CC_RING, CC_TIMECODE, CC_ASSIGN_L, CC_ASSIGN_R, NOTE_RUDE_SOLO,
                           NOTE_SEND, NOTE_F1, NOTE_MARKER, NOTE_NUDGE, NOTE_CYCLE, NOTE_DROP, NOTE_REPLACE,
                           NOTE_CLICK, NOTE_REW, NOTE_FF, NOTE_STOP, NOTE_PLAY, NOTE_RECORD, NOTE_UP,
                           NOTE_DOWN, NOTE_LEFT, NOTE_RIGHT, NOTE_ZOOM, NOTE_SCRUB, TRANSPORT_NOTES,
                           NOTE_DISPLAY, NOTE_SAVE, NOTE_ENTER)
# Étape 6 : MIDI, envoi vers la X-Touch et textes affichés dans surface/ (réexportés : D.Surface, D.seg_codes…)
from surface.display import ascii7, fader_text, rgb_to_xtouch, SIDE_NAMES, gain_label, seg_codes, time_display
from surface.midi import WinMidiIn, SafeMidi
from surface.xtouch import METER_REFRESH, FADER_TOL
from surface import xtouch as _xtouch
from bridge.journal import JOURNAL_SKIP, Journal, JournalSlot, JOURNAL
# FADER_CURVE / INF_POS : PAS réexportés (load_fader_curve les remplace dans bridge.values : lire _values.FADER_CURVE)
from bridge.values import (METER_STEPS, db_to_fader, CURVE_FILE, FADER_MIN_DB, load_fader_curve, fader_to_db,
                           db_to_level, LV1_PAN_SCALE, pan_label)
from bridge import values as _values
from bridge.gain import GainControl
from bridge.sends import flip_target, send_label, aux_short, SendControl

VERSION = "0.3"
# Dossier des fichiers de Joseph (réglages, courbe, journaux, reaper/) : à côté de l'exe une fois compilé (build.py)
HERE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
COLOR_FILE = os.path.join(HERE, "xtouch_couleurs.json")


METER_STALE = 1.0       # s : voie de vumètre qui n'arrive plus = disparue (stéréo -> mono)
TICK = 0.05             # 20 rafraîchissements par seconde


# ─── Conversions ──────────────────────────────────────────────────────────────

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

class LV1Model:
    """Ce que la LV1 dit par le réseau (MyFOH) : pistes, vumètres, envois, couches, User Keys, scènes. Rempli par
    handle() sous state.lock. Étape 7 du refactor (19/10/2026) : une des trois parties de LV1State."""

    def _init_lv1(self):
        self.connected = False
        self.tracks = {}          # (g, ch) -> {"name", "rgb", "pal", "fader"}
        self.meters = {}          # (g, ch, sub) -> dB
        self.meters_t = {}        # (g, ch, sub) -> instant de la dernière valeur reçue
        # Couches reçues, par (vue, custom) : vue 0 = Mixer 1, 1 = Mixer 2 ; custom 0 = usine, 1 = perso.
        # Hypothèse tirée du journal du 14/10 : le 1er nombre de /Notify/Layers est la vue.
        self.last_set = {}        # vue -> dernier jeu de couches reçu [(nom, [(g, ch) | None, ...]), ...]
        self.last_flag = {}       # vue -> 2e nombre de ce paquet (1 = custom d'après le module Companion)
        self.pending_set = {}     # vue -> (jeu, flag) reçu, adopté au /Notify/CurrentLayer qui le suit
        self.current = {}         # vue -> index de couche (/Notify/CurrentLayer)
        self.sends = {}           # (g, ch, aux) -> {"fader": dB, "on": bool, "pan": -1..1} (envois aux)
        self.aux_tracks = []      # /Aux/Tracks : [(groupe, canal, nom)] dans l'ordre des index aux (Fx 1-8, Mon 1-16)
        self.user_keys = {}       # n° 0..15 -> (nom court, fonction, assignée) : /Notify/UserKeyInfo
        self.scenes = {}          # index -> nom (/Notify/SceneList, /Notify/Scene/Name)
        self.cur_scene = None     # index de la scène courante (/Notify/CurSceneIndex), -1 = aucune
        self.scene_last = (None, 0.0)   # (index, instant) du dernier rappel retenu
        self.channels_at = 0.0    # instant du dernier /Channels (état complet renvoyé : connexion, Flip A/B…)
        self.custom_on = {}       # vue -> bouton Custom allumé ? (/Notify/CustomButton, hypothèse)
        self.spill_on = {}        # vue -> bouton Spill allumé ? (/Notify/SpillButton, hypothèse)
        self.version = ""

    def send(self, g, ch, aux):
        return self.sends.setdefault((g, ch, aux), {"fader": None, "on": None, "pan": None})

    def meter(self, g, ch, sub):
        """Dernier niveau reçu, ou None s'il n'arrive plus (piste stéréo remise en mono : sa voie droite n'est plus
        envoyée, remarque de Joseph du 15/10 — l'overlay gardait 2 vumètres). À appeler sous le verrou."""
        t = self.meters_t.get((g, ch, sub))
        if t is not None and time.time() - t > METER_STALE:
            return None
        return self.meters.get((g, ch, sub))

    def fader_of(self, key):
        """Fader d'une piste (g, ch) ou d'un envoi (g, ch, aux)."""
        d = self.sends.get(key) if len(key) == 3 else self.tracks.get(key)
        return (d or {}).get("fader")

    def set_fader(self, key, db):
        (self.send(*key) if len(key) == 3 else self.track(*key))["fader"] = db

    def track(self, g, ch):
        return self.tracks.setdefault((g, ch), {"name": None, "rgb": None, "pal": None, "fader": None,
                                                "mute": None, "solo": None, "pan": None})

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


class ScreenModel:
    """Ce que le pont lit lui-même, à l'écran ou dans la base de la LV1 (CurrentLV1.dat, sur copie) : Mixer suivi,
    onglet, voyant Spill, mode de couche, nombre de canaux, entrées A/B, routing du pilote. Partie de LV1State."""

    def _init_screen(self):
        self.view = 0             # Mixer suivi : 0 = Mixer 1, 1 = Mixer 2 (ViewFollower : onglet affiché, 18/10)
        self.lv1_tab = None       # onglet affiché par la LV1, lu à l'écran (« Mixer 1 », « All »…)
        self.spill_lit = False    # bouton Spill allumé sur la LV1, lu à l'écran (la base ne l'écrit pas)
        self.layer_mode = {}      # vue -> mode de couche lu dans la base (lv1_db.MODE_* ; touches View de la X-Touch)
        self.n_inputs = None      # canaux d'entrée configurés (16 / 32 / 64 / 80), base LV1
        self.on_b = None          # entrées sur B ? (base LV1, relue après chaque Flip A/B) ; None = inconnu
        self.routing = {}         # canal -> {"rec": [...], "play": [...]} (pilote SoundGrid de ce PC, base LV1)
        self.driver_size = None   # nb de canaux de lecture du pilote (diagonale B : lignes 1..n)


class BridgeState:
    """Ce qui n'existe que dans le pont : banque ◄ BANK ► locale, sélection, faders tenus et retours périmés, pan
    bloqué après un geste, scènes à transmettre à REAPER. Partie de LV1State."""

    def _init_bridge(self):
        self.local = {}           # vue -> index choisi par ◄ BANK ► sur la X-Touch (effacé au clic LV1)
        self.selected = None      # (g, ch) sélectionné dans le pont (Select / ◄ CHANNEL ►), local comme MyFOH
        self.held_tracks = set()  # (g, ch) dont le fader X-Touch est sous le doigt : retours LV1 ignorés
        # (g, ch) -> (valeurs « périmées » en dB arrondi, instant de fin) : après le relâchement, un retour
        # LV1 égal à l'ancienne valeur ou à une valeur intermédiaire du geste est ignoré (retour tardif).
        self.stale = {}
        self.pan_hold = {}        # (g, ch) -> instant jusqu'auquel les /Notify/Track/Pan sont ignorés (geste PAN)
        self.scene_events = []    # [(index, instant)] scènes rappelées sur la LV1, à transmettre à Reaper

    def bank(self, page, step):
        """◄ BANK ► : couche précédente / suivante du jeu affiché, en sautant les couches vides.

        Purement local : aucune commande LV1 connue pour changer de couche (module Companion du
        29/09/2026). L'écran LV1 ne bouge pas ; un clic de couche sur la LV1 reprend la main.
        Renvoie le nouvel index, ou None si on est déjà au bout."""
        layers, _ = self.layer_set(page)
        if not layers:
            return None
        idx = self.local.get(page, self.current.get(page, 0))
        k = idx + step
        while 0 <= k < len(layers):
            if any(layers[k][1]):
                self.local[page] = k
                return k
            k += step
        return None

    def layer_entries(self, mixer_page):
        """Les 16 tranches de la couche affichée, ou (None, None) si inconnue."""
        idx = self.local.get(mixer_page, self.current.get(mixer_page))
        layers, kind = self.layer_set(mixer_page)
        if idx is None or not layers:
            return None, None
        if 0 <= idx < len(layers):
            name, entries = layers[idx]
            if not any(entries):
                name += " (vide)"
            if mixer_page in self.local and self.local[mixer_page] != self.current.get(mixer_page):
                name += " (banque X-Touch)"
            return name, entries
        return None, None


class LV1State(LV1Model, ScreenModel, BridgeState):
    """Tout l'état partagé du pont (un seul objet `state`, un seul verrou). Les trois parties disent d'où vient chaque
    valeur ; on y accède toujours par `state.xxx` (noms inchangés à l'étape 7)."""

    def __init__(self):
        self.lock = threading.Lock()
        self._init_lv1()
        self._init_screen()
        self._init_bridge()


class FollowsView:
    """Objets qui suivent le Mixer affiché : leur `page` EST `state.view` (une seule valeur pour tout le pont).

    Hérité par LV1Clicker, LayerModeWatcher, LV1SelectionWatcher et ButtonControl : avant (18/10) chacun avait sa
    copie de la propriété, donc quatre endroits à corriger. `self.page = n` au démarrage impose la vue de départ
    (option --mixer)."""

    @property
    def page(self):
        return self.state.view

    @page.setter
    def page(self, value):
        self.state.view = value


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


def handle(state, address, args):
    JOURNAL.write(address, args)
    if address == "/Notify/Meters":
        now = time.time()
        with state.lock:
            for i in range(1, len(args) - 3, 4):
                g, c, s, d = args[i], args[i + 1], args[i + 2], args[i + 3]
                if g[0] == "i" and c[0] == "i" and s[0] == "i" and d[0] == "f":
                    state.meters[(g[1], c[1], s[1])] = d[1]
                    state.meters_t[(g[1], c[1], s[1])] = now
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
        elif address == "/Aux/Tracks" and args and args[0][0] == "i":
            # i:N puis par aux (i canal, i groupe, s nom) ; index aux = ordre (Fx 1-8 = 0..7, Mon 1-16 = 8..23)
            aux = []
            for k in range(1, len(args) - 2, 3):
                if args[k][0] == "i" and args[k + 1][0] == "i" and args[k + 2][0] == "s":
                    aux.append((args[k + 1][1], args[k][1], args[k + 2][1]))
            if aux:
                state.aux_tracks = aux
        elif address == "/Notify/SceneList" and args and args[0][0] == "i":
            # i:N puis (i index, s nom) x N — ex. i:2 i:0 "Scene Teste A" i:1 "Scene Teste B" (module Companion)
            scenes = {}
            for k in range(1, len(args) - 1, 2):
                if args[k][0] == "i" and args[k + 1][0] == "s":
                    scenes[args[k][1]] = args[k + 1][1]
            state.scenes = scenes
        elif address == "/Notify/Scene/Name" and args and args[0][0] == "s":
            if state.cur_scene is not None and state.cur_scene >= 0:
                state.scenes[state.cur_scene] = args[0][1]
        elif address == "/Notify/CurSceneIndex" and args and args[0][0] == "i":
            # Scène rappelée. La LV1 renvoie aussi la scène courante dans chaque état complet (connexion, Flip A/B) :
            # là, seul un CHANGEMENT d'index compte ; sinon tout rappel compte (même scène rappelée à nouveau).
            # Un rappel envoie CurSceneIndex TROIS fois en ~0,15 s (journal 155042) : une seule fois compte.
            idx, prev, now = args[0][1], state.cur_scene, time.time()
            dump = now - state.channels_at < 2.0
            state.cur_scene = idx
            last_idx, last_t = state.scene_last
            repeat = idx == last_idx and now - last_t < 1.0
            if prev is not None and idx >= 0 and (idx != prev or not dump) and not repeat:
                state.scene_events.append((idx, now))
                state.scene_last = (idx, now)
            elif repeat:
                state.scene_last = (idx, now)
        elif address == "/Notify/UserKeyInfo" and len(args) >= 4 and args[0][0] == "i":
            # ,issi [n°, nom court, fonction, assignée] ; ex. i:0 "Mon 1" "Flip Sends: MX1: Mon 1" i:1
            state.user_keys[args[0][1]] = (args[1][1], args[2][1], bool(args[3][1]))
        elif address == "/Notify/Aux/Send/Gain" and len(args) >= 4 and args[3][0] in "fdi":
            # ,iiid [g, ch, aux, dB] : mêmes garde-fous que les faders de piste (geste en cours, valeur périmée)
            key = (args[0][1], args[1][1], args[2][1])
            val = float(args[3][1])
            st = state.stale.get(key)
            if key in state.held_tracks:
                JOURNAL.mark("retour LV1 ignoré %s %s (fader tenu)" % (key, val))
            elif st and time.time() < st[1] and round(val, 1) in st[0]:
                JOURNAL.mark("retour LV1 ignoré %s %s (valeur périmée)" % (key, val))
            else:
                state.send(*key)["fader"] = val
        elif address == "/Notify/Aux/Send/On" and len(args) >= 4:
            on = args[3][0] == "T" or (args[3][0] == "i" and args[3][1] != 0)
            state.send(args[0][1], args[1][1], args[2][1])["on"] = on
        elif address == "/Notify/Aux/Send/Pan" and len(args) >= 4 and args[3][0] in "fd":
            key = (args[0][1], args[1][1], args[2][1])
            if time.time() >= state.pan_hold.get(key, 0):
                state.send(*key)["pan"] = max(-1.0, min(1.0, float(args[3][1]) / LV1_PAN_SCALE))
        elif address == "/Notify/Track/Pan" and len(args) >= 3 and args[2][0] in "fd":
            # ,iidi [groupe, canal, pan -45..+45, ?] ; la LV1 ne l'envoie qu'aux changements (pan de départ :
            # base de la LV1, lv1_db). Juste après un geste PAN, nos propres retours tardifs sont ignorés.
            key = (args[0][1], args[1][1])
            if time.time() >= state.pan_hold.get(key, 0):
                state.track(*key)["pan"] = max(-1.0, min(1.0, float(args[2][1]) / LV1_PAN_SCALE))
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
            state.channels_at = time.time()
            count = args[0][1]
            for k in range(max(0, min(count, 256))):
                base = 1 + k * 19
                if base + 3 >= len(args):
                    break
                n, g, c, f = args[base], args[base + 1], args[base + 2], args[base + 3]
                if n[0] == "s" and g[0] == "i" and c[0] == "i":
                    t = state.track(g[1], c[1])
                    t["name"] = n[1]
                    # 1er double = fader en dB (-144 = -inf). Pris à CHAQUE /Channels, pas seulement au départ :
                    # un rappel de scène ne renvoie les nouveaux niveaux QUE là (remarque de Joseph du 15/10 :
                    # faders immobiles après un rappel). Sauf fader sous le doigt.
                    if f[0] == "d" and (g[1], c[1]) not in state.held_tracks:
                        t["fader"] = f[1]
                    # Vérifié le 14/10/2026 (journaux 173028 -> 173215) : des 12 entiers,
                    # le 1er = solo, le 2e = mute (0|1). Seul moyen d'avoir l'état à la connexion.
                    if base + 6 >= len(args):
                        break
                    so, mu = args[base + 5], args[base + 6]
                    if so[0] == "i":
                        t["solo"] = so[1] != 0
                    if mu[0] == "i":
                        t["mute"] = mu[1] != 0
                    # 12e entier : 1 = mono, 2 = stéréo (vérifié le 15/10 : P170 ST et Channel 11 = 2)
                    if base + 16 < len(args) and args[base + 16][0] == "i":
                        t["stereo"] = args[base + 16][1] == 2
        elif address == "/Notify/Layers":
            # Jeu adopté SEULEMENT s'il est suivi de /Notify/CurrentLayer pour la même vue (bug du 15/10, journal
            # 155042) : dans un état complet (connexion, rappel de scène, Flip A/B), la LV1 envoie les jeux d'usine
            # suivis de CurrentLayer, PUIS les pages Custom SANS CurrentLayer -> « dernier jeu reçu » affichait à
            # tort Custom Page-1. Un vrai passage en Custom envoie bien Layers (Custom) + CurrentLayer.
            page, is_custom, layers = parse_layers(args)
            if layers:
                state.pending_set[page] = (layers, is_custom)
        elif address == "/Notify/CustomButton" and len(args) >= 2 and args[1][0] == "i":
            state.custom_on[args[0][1]] = args[1][1] != 0
        elif address == "/Notify/SpillButton" and len(args) >= 2 and args[1][0] == "i":
            state.spill_on[args[0][1]] = args[1][1] != 0
        elif address == "/Notify/CurrentLayer" and len(args) >= 2:
            pend = state.pending_set.pop(args[0][1], None)
            if pend:
                state.last_set[args[0][1]], state.last_flag[args[0][1]] = pend
            state.current[args[0][1]] = args[1][1]
            state.local.pop(args[0][1], None)   # clic de couche sur la LV1 : elle reprend la main
        elif address == "/Notify/ServiceVersion" and args and args[0][0] == "s":
            state.version = args[0][1]


# ─── Lien réseau avec la LV1 (lecture seule, reconnexion automatique) ────────

class LV1Link(threading.Thread):
    # Vu le 15/10/2026 (journaux 001220, 001435) : juste après un redémarrage de la LV1, elle accepte la connexion
    # mais n'envoie PAS son état (/Channels, /Notify/Layers, couleurs) -> plus de couleurs ni de banques. Si rien
    # n'arrive : on redemande à STATE_ASK s, puis on se reconnecte à STATE_GIVEUP s (nouvelle poignée de main).
    # État complet = /Channels ET /Notify/Layers (journal 230733 du 15/10 : après un « /Device/LinkSettings/NewSession »
    # la LV1 a envoyé canaux et couleurs puis PLUS RIEN — ni couches, ni scènes, ni User Keys -> SAVE sans « Store »)
    # ET /Notify/UserKeyInfo (19/10, journal 113310 : couches reçues sur /Get/Layers, User Keys JAMAIS -> FLIP sans
    # effet, « aucune User Key Flip AB »). La LV1 envoie les 16 User Keys même non assignées (« None », 17/10), mais
    # aucune demande connue ne les fait renvoyer : seule une reconnexion. Si elles manquent encore après KEYS_TRIES
    # reconnexions, l'état est accepté sans elles (pas de boucle de reconnexion sur une LV1 qui ne les enverrait pas).
    STATE_MSGS = ("/Channels", "/Notify/Layers", "/Notify/UserKeyInfo")
    STATE_ASK, STATE_GIVEUP = 5.0, 10.0
    KEYS_TRIES = 2

    def state_complete(self, seen):
        """Canaux + couches reçus, et User Keys reçues (ou déjà KEYS_TRIES reconnexions pour elles seules)."""
        if "/Channels" not in seen or "/Notify/Layers" not in seen:
            return False
        return "/Notify/UserKeyInfo" in seen or self.keys_missing >= self.KEYS_TRIES

    def __init__(self, state, host=None, port=None, name="XTouch-Display"):
        super().__init__(daemon=True)
        self.state = state
        self.host, self.port = host, port
        self.name_ = name
        self.stop_flag = False
        self.sock = None
        self.send_lock = threading.Lock()
        self.on_connect = None    # appelée (sur un fil à part) à chaque connexion : pans de départ…
        self.keys_missing = 0     # reconnexions faites pour les seules User Keys (remis à 0 quand elles arrivent)

    def send(self, address, args):
        """Envoie un message à la LV1 (ignoré si pas connectée)."""
        with self.send_lock:
            if self.sock is None:
                return False
            try:
                self.sock.sendall(osc.frame(address, args))
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
            sock.sendall(osc.frame("/handshake", [("i", 1), ("i", -1), ("i", 1)]) +
                         osc.frame("/device_name", [("s", self.name_), ("s", "XTOUCH-LV1-DISPLAY-0001")]))
            asked = False
            t_ack = time.time() + 3
            got_state, t_conn, reasked, seen = False, None, False, set()
            while not self.stop_flag:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    chunk = None
                if chunk == b"":
                    raise OSError("la LV1 a fermé la connexion")
                if chunk:
                    buf += chunk
                    packets, buf = osc.split_frames(buf)
                    for p in packets:
                        try:
                            address, args = osc.osc_decode(p)
                        except Exception:
                            continue
                        if address == "/ping":
                            with self.send_lock:
                                sock.sendall(osc.frame("/pong", args))
                        elif address == "/handshake" and args[:1] == [("i", 1)]:
                            ack.set()
                        else:
                            if address in self.STATE_MSGS:
                                seen.add(address)
                                got_state = self.state_complete(seen)
                                if address == "/Notify/UserKeyInfo":
                                    self.keys_missing = 0
                            handle(self.state, address, args)
                if ack.is_set() and not asked:
                    asked = True
                    with self.send_lock:
                        self.sock = sock
                    with self.state.lock:
                        self.state.connected = True
                    print("  LV1 connectée (%s:%d)" % (ip, port))
                    if self.on_connect:
                        threading.Thread(target=self.on_connect, daemon=True).start()
                    sock.sendall(osc.frame("/Get/Aux/Tracks") + osc.frame("/Get/Layers", [("i", 0), ("i", 0)]))
                    t_conn = time.time()
                if t_conn and not got_state:
                    waited = time.time() - t_conn
                    if waited > self.STATE_GIVEUP:
                        if "/Channels" in seen and "/Notify/Layers" in seen:     # seules les User Keys manquent
                            self.keys_missing += 1
                            JOURNAL.mark("User Keys LV1 non reçues : reconnexion %d / %d" % (self.keys_missing,
                                                                                            self.KEYS_TRIES))
                        JOURNAL.mark("état initial LV1 non reçu en %.0f s : reconnexion" % waited)
                        raise OSError("la LV1 n'envoie pas son état (en cours de chargement ?) : reconnexion")
                    if waited > self.STATE_ASK and not reasked:
                        reasked = True
                        JOURNAL.mark("état initial LV1 non reçu : nouvelle demande")
                        with self.send_lock:
                            sock.sendall(osc.frame("/Get/Aux/Tracks") + osc.frame("/Get/Layers", [("i", 0), ("i", 0)]))
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

class Surface(_xtouch.Surface):
    """surface.xtouch.Surface + journal des commandes moteur (le journal est remplacé au démarrage : lu à l'appel)."""

    def motor_note(self, what, value):
        JOURNAL.mark("moteur %s -> %d (%s dB)" % (what, value, fader_to_db(value)))


# ─── Entrée MIDI (faders, toucher, boutons) ───────────────────────────────────

EVENTS = queue.Queue()  # messages MIDI reçus (global : les tests peuvent en injecter)
HOLD_AFTER = 0.3        # s pendant lesquelles un fader lâché reste « tenu » (retours LV1 ignorés)
MOTOR_BUSY = 1.5        # s après une commande moteur : un fader bougé sans toucher est le moteur, pas la main
NAIL_SHOW = 0.15        # s : point de toucher d'un fader bougé sans toucher détecté, après son dernier mouvement
UNTOUCHED_MIN = 80      # écart (sur 16383) qu'un fader non touché doit faire pour démarrer un geste (ongle)
STALE_FOR = 2.0         # s après le relâchement pendant lesquelles un retour « périmé » est ignoré
SEND_EVERY = 0.02       # envoi max d'une valeur par fader toutes les 20 ms


def master_display(selected, gain_db, side, stereo, lr_db):
    """Option C : (2 car. assignment, 10 car. timecode) = n° du canal sélectionné ; son gain X32 (5) + fader LR (5)."""
    if selected is None:
        num = "--"
    elif selected[0] == 0:
        num = "%2d" % (selected[1] + 1) if selected[1] < 99 else "99"
    else:
        num = "%s%d" % ({1: "G", 2: "F", 3: "LR", 5: "M", 6: "T", 12: "D", 25: "A"}.get(selected[0], "?"),
                        selected[1] + 1)
    if gain_db is None:
        g = "  -  "
    else:
        g = ("%s%.1f" % ("LR"[side] if stereo else "", gain_db))
    if lr_db is None:
        lr = "  -"
    elif lr_db <= -144:
        lr = " -oo"
    else:
        lr = "%.1f" % lr_db
    left = seg_codes(g, 5)
    right = seg_codes(lr, 5)
    return seg_codes(num[-2:], 2), left + right


def layer_toast(layer_name):
    """Nom de couche du pont -> nom seul pour la notification (Joseph, 16/10 : « juste le nom du layer »), sans les
    mentions « (banque X-Touch) » / « (vide) » ; None si la couche n'est pas encore connue."""
    if not layer_name or layer_name.endswith("(par défaut)"):
        return None
    for suffix in (" (banque X-Touch)", " (vide)"):
        if layer_name.endswith(suffix):
            layer_name = layer_name[:-len(suffix)]
    return layer_name


# Le négatif (couleur + 0x20) n'a AUCUN effet en mode Mackie (essai de Joseph, 15/10) : à la place, la ligne du
# bas affiche l'aux devant le niveau d'envoi.


class LV1Clicker(FollowsView, threading.Thread):
    """Fait suivre la LV1 par clics simulés (option --clic-lv1) : couche (BANK) et sélection (Select, CHANNEL).

    L'API réseau n'a pas ces commandes (Companion, capture MyFOH du 14/10). lv1_clic.py clique dans la fenêtre
    LV1 (message Windows, la souris ne bouge pas), avec ses garde-fous (administrateur, onglet Mixer lu à
    l'écran, case présente). Une file à part : jamais de clic dans la boucle MIDI. Une tranche n'est cliquée
    que si la LV1 affiche la couche qui la contient (sinon le clic sélectionnerait un autre canal)."""
    WAIT_LAYER = 1.0     # s d'attente de /Notify/CurrentLayer après un clic de couche

    def __init__(self, state, page, click_layer=None, click_strip=None, jog=None, jog_method="message",
                 click_mode=None, click_all=None):
        # click_strip(i, mixer, rgb=...) : couleur du canal (0..255) pour trouver la bande du nom à l'écran.
        # Bug du 15/10 : passée en 3e position, elle tombait dans « method » -> aucune sélection cliquée.
        # click_mode(nom, n_inputs, mixer) : bouton Input / Mix / Factory / Custom / Spill (touches View) ;
        # click_all(mixer) : onglet All <-> Mixer N (GLOBAL VIEW).
        super().__init__(daemon=True)
        self.state, self.page = state, page
        if None in (click_layer, click_strip, click_mode, click_all):
            import lv1_clic
            click_layer = click_layer or lv1_clic.click_layer
            click_strip = click_strip or lv1_clic.click_strip
            click_mode = click_mode or lv1_clic.click_mode
            click_all = click_all or lv1_clic.toggle_all_tab
        self.click_layer, self.click_strip, self.click_mode = click_layer, click_strip, click_mode
        self.click_all = click_all
        if jog is None:
            import lv1_clic
            jog = lambda n: lv1_clic.jog_bottom_fader(n, self.page + 1, jog_method)
        self.jog_fn = jog
        self.jog_fallback = None     # jog refusé (pas de fader de plugin à l'écran) -> Reaper (TransportControl.jog)
        self.q = queue.Queue()
        self.last_why = None

    def layer(self, k):
        self.q.put(("couche", k))

    def mode(self, name):
        """Bouton de mode de couche de la LV1 : input, mix, factory, custom, spill."""
        self.q.put(("mode", name))

    def all_tab(self):
        """Onglet All de la LV1, ou retour sur Mixer N si All est déjà affiché."""
        self.q.put(("onglet", None))

    def jog(self, notches):
        """Jog wheel : crans de molette sur le fader de plugin du bas de la page Channel."""
        if notches:
            self.q.put(("jog", notches))

    def select(self, track):
        if track is not None:
            self.q.put(("sélection", track))

    def _refused(self, what, why):
        JOURNAL.mark("clic LV1 %s refusé : %s" % (what, why))
        if why != self.last_why:
            print("  Clic LV1 impossible (%s) : %s" % (what, why))
            self.last_why = why

    def run(self):
        while True:
            kind, arg = self.q.get()
            if kind == "sélection":          # on ne garde que la dernière sélection en attente
                try:
                    while True:
                        nxt = self.q.queue[0]
                        if nxt[0] != "sélection":
                            break
                        kind, arg = self.q.get_nowait()
                except IndexError:
                    pass
            if kind in ("mode", "onglet"):       # appuis répétés en attente (journal du 16/10 : 12 appuis sur GROUP
                n = 1                            # exécutés un par un pendant 30 s) : regroupés
                try:
                    while self.q.queue and self.q.queue[0] == (kind, arg):
                        self.q.get_nowait()
                        n += 1
                except (IndexError, queue.Empty):
                    pass
                if n % 2 == 0 and (kind == "onglet" or arg in ("custom", "spill")):
                    JOURNAL.mark("clic LV1 %s %s : %d appuis, bascule annulée" % (kind, arg or "", n))
                    continue                     # bascule : un nombre pair d'appuis revient au même
            if kind == "jog":                    # crans rapides regroupés en un seul envoi
                try:
                    while self.q.queue and self.q.queue[0][0] == "jog":
                        arg += self.q.get_nowait()[1]
                except (IndexError, queue.Empty):
                    pass
            try:
                if kind == "jog":
                    if arg:
                        ok, why = self.jog_fn(arg)
                        JOURNAL.mark("molette LV1 %+d : %s" % (arg, "envoyée" if ok else why))
                        if not ok and self.jog_fallback:
                            self.jog_fallback(arg)       # choix de Joseph : jog selon la page LV1
                        elif not ok:
                            self._refused("jog", why or "envoi refusé par Windows")
                    continue
                if kind == "onglet":
                    ok, why = self.click_all(self.page + 1)
                    JOURNAL.mark("clic LV1 onglet All / Mixer : %s" % (("envoyé" + (" (%s)" % why if why else "")) if ok else why))
                    if not ok:
                        self._refused("onglet All", why or "envoi refusé par Windows")
                    continue
                if kind == "mode":
                    with self.state.lock:
                        n = self.state.n_inputs
                    ok, why = self.click_mode(arg, n, self.page + 1)
                    JOURNAL.mark("clic LV1 mode %s : %s" % (arg, ("envoyé" + (" (%s)" % why if why else "")) if ok else why))
                    if not ok:
                        self._refused("mode %s" % arg, why or "envoi refusé par Windows")
                    else:
                        self.last_why = None
                    continue
                if kind == "couche":
                    with self.state.lock:
                        if self.state.current.get(self.page) == arg:
                            continue
                    ok, why = self.click_layer(arg, self.page + 1)
                    JOURNAL.mark("clic LV1 couche %d : %s" % (arg + 1, ("envoyé" + (" (%s)" % why if why else "")) if ok else why))
                    if not ok:
                        self._refused("couche", why or "envoi refusé par Windows")
                        continue
                    t_end = time.time() + self.WAIT_LAYER
                    while time.time() < t_end:
                        with self.state.lock:
                            if self.state.current.get(self.page) == arg:
                                break
                        time.sleep(0.02)
                else:
                    with self.state.lock:
                        layers, _ = self.state.layer_set(self.page)
                        idx = self.state.current.get(self.page)
                        ent = layers[idx][1] if layers and idx is not None and 0 <= idx < len(layers) else []
                    i = ent.index(arg) if arg in ent else None
                    if i is None or i >= 16:
                        JOURNAL.mark("clic LV1 sélection %s : pas sur la couche affichée par la LV1" % (arg,))
                        continue
                    with self.state.lock:
                        f = self.state.tracks.get(arg, {}).get("rgb")
                    rgb = tuple(int(round(v * 255)) for v in f) if f else None
                    ok, why = self.click_strip(i, self.page + 1, rgb=rgb)   # mot-clé : 3e paramètre = méthode
                    JOURNAL.mark("clic LV1 tranche %d %s : %s" % (i + 1, arg, ("envoyé" + (" (%s)" % why if why else "")) if ok else why))
                    if not ok:
                        self._refused("sélection", why or "envoi refusé par Windows")
                    else:
                        self.last_why = None
            except Exception as e:           # un clic raté ne doit jamais arrêter le pont
                JOURNAL.mark("clic LV1 : erreur %r" % e)


class LayerModeWatcher(FollowsView, threading.Thread):
    """Mode de couche de la vue suivie (Input / Mix / Factory / Custom / Spill) et nombre de canaux configuré, lus
    dans la base de la LV1 (copie) chaque fois qu'elle change : voyants des touches View, bouton à cliquer.
    Le réseau ne le donne pas (/Notify/CustomButton et /Notify/SpillButton ne bougent pas, vérifié le 14/10)."""
    PERIOD = 0.5

    def __init__(self, state, page, read=None, stamp=None, tab=None, spill=None):
        super().__init__(daemon=True)
        self.state, self.page = state, page
        if read is None or stamp is None:
            import lv1_db
            read = read or (lambda: lv1_db.layer_mode(self.page + 1))
            stamp = stamp or lv1_db.db_stamp
        if spill is None and sys.platform == "win32":
            import lv1_clic
            spill = lambda: lv1_clic.spill_on(self.page + 1)               # voyant GROUP (pas dans la base)
        # tab : onglet affiché (voyant GLOBAL VIEW) ; en vrai c'est ViewFollower qui le lit (tests : injecté)
        self.read, self.stamp, self.tab, self.spill = read, stamp, tab, spill
        self.last = object()

    def step(self):
        if self.tab:
            try:
                t = self.tab()
            except Exception:
                t = None
            if t is not None:                                # illisible (LV1 cachée) : on garde le dernier
                with self.state.lock:
                    self.state.lv1_tab = t
        if self.spill:
            try:
                sp = self.spill()
            except Exception:
                sp = None
            if sp is not None:                               # page Mixer pas affichée : on garde le dernier
                with self.state.lock:
                    self.state.spill_lit = sp
        st = (self.stamp(), self.page)                     # autre Mixer suivi : relire son mode
        if st == self.last:
            return
        try:
            mode, n = self.read()
        except Exception as e:              # base absente ou en cours d'écriture : on réessaiera au prochain changement
            JOURNAL.mark("mode de couche illisible : %r" % e)
            return
        self.last = st
        with self.state.lock:
            changed = (self.state.layer_mode.get(self.page), self.state.n_inputs) != (mode, n)
            self.state.layer_mode[self.page] = mode
            self.state.n_inputs = n
        if changed:
            JOURNAL.mark("mode de couche (base LV1) : %s, %s canaux" % (mode, n))

    def run(self):
        while True:
            self.step()
            time.sleep(self.PERIOD)


class ViewFollower(threading.Thread):
    """Mixer suivi par tout le pont (demande de Joseph du 18/10 : tout ce qui marche sur Mixer 1 aussi sur Mixer 2) :
    onglet Mixer 1 / Mixer 2 de la fenêtre principale, ou fenêtre Mixer détachée (« MIXER1 » / « MIXER2 ») au premier
    plan ; autre onglet (Channel, All…) : le dernier Mixer reste suivi. fixed = 0 / 1 (--mixer 1 / 2) : vue imposée.
    Met aussi à jour state.lv1_tab (voyant GLOBAL VIEW). Limite : avec un Mixer détaché, la fenêtre principale a moins
    d'onglets (positions décalées) -> son onglet peut être mal lu (cas 2 écrans, hors de l'usage de Joseph)."""
    PERIOD = 0.2

    def __init__(self, state, fixed=None, read=None):
        super().__init__(daemon=True)
        self.state, self.fixed = state, fixed
        if read is None:
            import lv1_clic
            read = lv1_clic.view_hint
        self.read = read

    def step(self):
        tab, front_mixer = self.read()
        new = None
        with self.state.lock:
            if tab is not None:                              # illisible (LV1 cachée) : on garde le dernier
                self.state.lv1_tab = tab
            if self.fixed is None:
                if front_mixer in (1, 2):
                    new = front_mixer - 1
                elif tab in ("Mixer 1", "Mixer 2"):
                    new = int(tab[-1]) - 1
                if new is None or new == self.state.view:
                    new = None
                else:
                    self.state.view = new
        if new is not None:
            JOURNAL.mark("Mixer suivi : Mixer %d" % (new + 1))
            print("  Mixer suivi : Mixer %d" % (new + 1))

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:
                JOURNAL.mark("lecture de l'onglet LV1 : erreur %r" % e)
            time.sleep(self.PERIOD)


def view_leds(mode, tab=None, spill=False):
    """Voyants des touches View : mode de couche (lv1_db.MODE_*), onglet affiché, Spill lu à l'écran ; {note: allumée}.
    Inconnu : éteint. Spill allumé : la base garde le mode d'avant (4), mais seul Spill est allumé sur la LV1 -> seul
    GROUP. GLOBAL VIEW = onglet All (Joseph, 16/10)."""
    spill = bool(spill or mode == 3)
    return {NOTE_INPUTS: mode in (0, 4) and not spill, NOTE_BUSES: mode == 5 and not spill,
            NOTE_USER: mode == 1 and not spill, NOTE_GROUP: spill, NOTE_GLOBAL_VIEW: tab == "All"}


class LV1SelectionWatcher(FollowsView, threading.Thread):
    """Sens LV1 -> X-Touch : la tranche sélectionnée sur l'écran de la LV1 (liseré jaune, lu à l'écran
    toutes les 0,15 s, sans administrateur) devient la sélection du pont (LED Select).

    On ne réagit qu'à un CHANGEMENT de la colonne lue : si la LV1 garde une sélection hors de la couche
    affichée par la X-Touch, elle n'écrase pas une sélection faite sur la X-Touch."""
    PERIOD = 0.15

    def __init__(self, state, page, read=None):
        super().__init__(daemon=True)
        self.state, self.page = state, page
        if read is None:
            import lv1_clic
            read = lambda: lv1_clic.selected_strip(self.page + 1)[0]
        self.read = read
        self.last = None
        self.last_page = None
        self.stop_flag = False

    def step(self):
        if self.page != self.last_page:                      # autre Mixer suivi : sa sélection repart de zéro
            self.last_page, self.last = self.page, None
        col = self.read()
        if col is None or col == self.last:
            if col is not None:
                self.last = col
            return
        self.last = col
        with self.state.lock:
            layers, _ = self.state.layer_set(self.page)
            idx = self.state.current.get(self.page)
            ent = layers[idx][1] if layers and idx is not None and 0 <= idx < len(layers) else []
            track = ent[col] if col < len(ent) else None
            if track is None or track == self.state.selected:
                return
            self.state.selected = track
        JOURNAL.mark("sélection lue sur la LV1 : tranche %d %s" % (col + 1, track))

    def run(self):
        while not self.stop_flag:
            try:
                self.step()
            except Exception as e:            # lecture d'écran ratée : on réessaie au tour suivant
                JOURNAL.mark("lecture sélection LV1 : erreur %r" % e)
            time.sleep(self.PERIOD)


# ─── Transport X-Touch -> REAPER (demande de Joseph, 15/10 : la surface coupée en deux, tranches = LV1,
# transport / navigation = Reaper pour le virtual soundcheck). Notes : surface/notes.py.


class TransportControl:
    """◄◄ ►► ■ ► ● -> transport Reaper (◄◄ / ►► tenus) ; CYCLE = boucle, CLICK = métronome ; DROP / REPLACE =
    In / Out de la boucle (position jouée en lecture).
    MARKER seul = poser un marqueur ; flèches ◄ ► = marqueur précédent / suivant, ▲ ▼ = piste précédente / suivante ;
    ZOOM (bascule) : ◄ ► = zoom horizontal, ▲ ▼ = zoom vertical. Jog -> Reaper hors fader de plugin LV1 :
    déplacement du curseur (SCRUB allumé : pas fin). LED = état renvoyé par Reaper."""

    def __init__(self, reaper):
        self.reaper = reaper
        self.zoom = self.scrub = False
        self.marker_down = self.marker_used = False

    def jog(self, notches):
        import reaper_link as R
        if self.scrub:
            act = R.ACT_SCRUB_FWD if notches > 0 else R.ACT_SCRUB_BACK
        else:
            act = R.ACT_JOG_FWD if notches > 0 else R.ACT_JOG_BACK
        for _ in range(min(abs(notches), 8)):
            self.reaper.action(act)

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        if (status & 0xF0) != 0x90 or d1 not in TRANSPORT_NOTES or unit != surface.master_unit:
            return False
        down = d2 > 0
        if not self.reaper:
            return True
        import reaper_link as R
        name = {NOTE_REW: "rewind", NOTE_FF: "forward"}.get(d1)
        if name:                                         # tenus : avance / retour rapide tant qu'on appuie
            self.reaper.hold(name, down)
            JOURNAL.mark("XT %s %s -> Reaper" % (name, "appui" if down else "relâché"))
            return True
        if d1 == NOTE_MARKER:
            if down:
                self.marker_down, self.marker_used = True, False
            else:
                if not self.marker_used:
                    self.reaper.action(R.ACT_ADD_MARKER)
                    JOURNAL.mark("XT Marker -> Reaper : marqueur posé")
                self.marker_down = False
            return True
        if not down:
            return True
        if d1 in (NOTE_STOP, NOTE_PLAY, NOTE_RECORD, NOTE_CYCLE, NOTE_CLICK):
            cmd = {NOTE_STOP: "stop", NOTE_PLAY: "play", NOTE_RECORD: "record", NOTE_CYCLE: "repeat",
                   NOTE_CLICK: "click"}[d1]
            self.reaper.trigger(cmd)
            JOURNAL.mark("XT %s -> Reaper" % cmd)
        elif d1 in (NOTE_DROP, NOTE_REPLACE):          # In / Out de la boucle (demande de Joseph, 15/10)
            self.reaper.action(R.ACT_EDIT_TO_PLAY)       # en lecture : à la position jouée (à l'arrêt : sans effet)
            self.reaper.action(R.ACT_LOOP_START if d1 == NOTE_DROP else R.ACT_LOOP_END)
            JOURNAL.mark("XT %s -> Reaper : %s de la boucle" % ("Drop" if d1 == NOTE_DROP else "Replace",
                                                                "In" if d1 == NOTE_DROP else "Out"))
        elif d1 == NOTE_ZOOM:
            self.zoom = not self.zoom
        elif d1 == NOTE_SCRUB:
            self.scrub = not self.scrub
        elif d1 in (NOTE_LEFT, NOTE_RIGHT, NOTE_UP, NOTE_DOWN):
            self.marker_used = True
            if self.zoom:
                act = {NOTE_LEFT: R.ACT_ZOOM_OUT_H, NOTE_RIGHT: R.ACT_ZOOM_IN_H,
                       NOTE_UP: R.ACT_ZOOM_IN_V, NOTE_DOWN: R.ACT_ZOOM_OUT_V}[d1]
            else:
                act = {NOTE_LEFT: R.ACT_PREV_MARKER, NOTE_RIGHT: R.ACT_NEXT_MARKER,
                       NOTE_UP: R.ACT_PREV_TRACK, NOTE_DOWN: R.ACT_NEXT_TRACK}[d1]
            self.reaper.action(act)
            JOURNAL.mark("XT flèche %02X -> Reaper action %d" % (d1, act))
        return True

    def leds(self):
        """{note: allumée} pour les boutons de transport."""
        st = self.reaper.state if self.reaper else {}
        return {NOTE_PLAY: st.get("play", False), NOTE_STOP: st.get("stop", False) and not st.get("play", False),
                NOTE_RECORD: st.get("record", False), NOTE_CYCLE: st.get("repeat", False),
                NOTE_CLICK: st.get("click", False), NOTE_ZOOM: self.zoom, NOTE_SCRUB: self.scrub,
                NOTE_MARKER: self.marker_down}


# ─── Bascule LV1 <-> Reaper et SAVE (demande de Joseph, 15/10) ──────────────────────────────────────────────────────
ACT_REAPER_SAVE_AS = 40022   # File: Save project as...


class AppControl:
    """DISPLAY = bascule du premier plan : LV1 devant -> Reaper ; sinon -> LV1. LED DISPLAY allumée = Reaper devant.
    SAVE : Reaper devant -> « Save project as » ; LV1 devant -> User Key de la LV1 dont la fonction contient « Store »
    (pas de commande réseau connue pour enregistrer une scène) ; autre fenêtre -> rien."""

    def __init__(self, state, link, reaper, mixer=1, write=True):
        self.state, self.link, self.reaper, self.mixer, self.write = state, link, reaper, mixer, write
        self.front = "autre"
        self.fixing = False
        self.warned = set()
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        import fenetres
        while True:
            self.front = fenetres.front_app(self.mixer)
            time.sleep(0.4)

    def _fix_diagonal(self):
        """ENTER : refait la diagonale B par clics (lv1_patch), page Patch > Input B ouverte (sinon refusé, sans clic)."""
        try:
            import lv1_patch
            ok, msg = lv1_patch.fix_diagonal(log=lambda m: JOURNAL.mark("diagonale B : " + m))
            JOURNAL.mark("XT Enter -> diagonale B : %s" % msg)
            print("  Diagonale B : %s" % msg)
        except Exception as e:
            JOURNAL.mark("XT Enter -> diagonale B : erreur %r" % e)
            print("  Diagonale B : erreur %r" % e)
        finally:
            self.fixing = False

    def _switch(self):
        import fenetres
        target = "lv1" if fenetres.front_app(self.mixer) == "reaper" else "reaper"
        ok = fenetres.bring(target, self.mixer)
        JOURNAL.mark("XT Display -> %s au premier plan : %s" % (target, "ok" if ok else "refusé / introuvable"))
        self.front = fenetres.front_app(self.mixer)

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        if (status & 0xF0) != 0x90 or d1 not in (NOTE_DISPLAY, NOTE_SAVE, NOTE_ENTER) or unit != surface.master_unit:
            return False
        if not d2:
            return True
        if d1 == NOTE_ENTER:
            if not self.fixing:
                self.fixing = True
                threading.Thread(target=self._fix_diagonal, daemon=True).start()
            return True
        if d1 == NOTE_DISPLAY:
            threading.Thread(target=self._switch, daemon=True).start()
            return True
        import fenetres
        front = fenetres.front_app(self.mixer)
        if front == "reaper":
            if self.reaper:
                self.reaper.action(ACT_REAPER_SAVE_AS)
                JOURNAL.mark("XT Save -> Reaper : Save project as")
        elif front == "lv1":
            with self.state.lock:
                keys = [k for k, (_s, func, on) in sorted(self.state.user_keys.items())
                        if on and "store" in (func or "").lower()]
            if keys and self.write:
                self.link.send("/Set/UserKey", [("i", keys[0]), ("T", True)])
                self.link.send("/Set/UserKey", [("i", keys[0]), ("F", False)])
                JOURNAL.mark("XT Save -> LV1 User Key %d (store)" % (keys[0] + 1))
            elif not keys:
                JOURNAL.mark("XT Save : aucune User Key « Store » dans la LV1")
                if "store" not in self.warned:
                    print("  SAVE : assigne une User Key de la LV1 à l'enregistrement de scène (fonction « Store … »).")
                    self.warned.add("store")
        else:
            JOURNAL.mark("XT Save ignoré : ni la LV1 ni Reaper au premier plan")
        return True


class ButtonControl(FollowsView):
    """Mute / Solo -> LV1 ; ◄ BANK ► -> couche, Select / ◄ CHANNEL ► -> sélection (locales). Rec : rien."""

    def __init__(self, state, link, write=True, page=0, busy=lambda: False):
        self.state, self.link, self.write = state, link, write
        self.page = page          # vue LV1 suivie (0 = Mixer 1) : state.view, partagée (propriété)
        self.busy = busy          # vrai si un fader est sous le doigt : pas de changement de banque
        self.lv1 = None           # LV1Clicker si --clic-lv1 : la LV1 suit couche et sélection
        self.transport = None     # TransportControl (Reaper) : reçoit le jog quand il ne va pas à la LV1
        self.reaper_tc = True     # afficheur : timecode de REAPER (s'il répond) ou heure ; touche SMPTE
        self.warned = set()

    def on_bank(self, d1):
        step = -1 if d1 == NOTE_BANK_LEFT else 1
        if self.busy():
            JOURNAL.mark("XT bouton Bank %+d ignoré (fader tenu)" % step)
            return True
        with self.state.lock:
            k = self.state.bank(self.page, step)
        JOURNAL.mark("XT bouton Bank %+d -> couche %s" % (step, k if k is not None else "inchangée (bout)"))
        if k is not None and self.lv1:
            self.lv1.layer(k)
        return True

    def on_view(self, d1):
        """Touches View -> bouton de mode de couche de la LV1 (clic simulé, --clic-lv1)."""
        with self.state.lock:
            n = self.state.n_inputs
        if d1 == NOTE_GLOBAL_VIEW:
            JOURNAL.mark("XT bouton Global View -> onglet All / Mixer")
            if self.lv1:
                self.lv1.all_tab()
            return
        name = {NOTE_INPUTS: "input" if n == 80 else "factory", NOTE_BUSES: "mix", NOTE_USER: "custom",
                NOTE_GROUP: "spill"}[d1]
        JOURNAL.mark("XT bouton View %02X -> mode %s (%s canaux)" % (d1, name, n))
        if name == "mix" and n != 80:
            JOURNAL.mark("mode Mix : seulement en 80 canaux")
            return
        if self.lv1:
            self.lv1.mode(name)
        elif "view" not in self.warned:
            print("  Touches INPUTS / BUSES / USER / GROUP / GLOBAL VIEW : avec --clic-lv1 seulement.")
            self.warned.add("view")

    def on_channel(self, d1, entries):
        """◄ CHANNEL ► : sélection au canal affiché précédent / suivant (tranches vides sautées).

        Si le canal sélectionné n'est pas affiché (ou aucun) : 1er canal de la couche affichée.
        Au bout de la couche, la banque suit (couche voisine non vide, 1er / dernier canal)."""
        step = -1 if d1 == NOTE_CHANNEL_LEFT else 1
        shown = [e for e in entries[:MASTER] if e is not None]
        kb = None
        with self.state.lock:
            sel = self.state.selected
            if sel not in shown:
                new = shown[0] if shown else None
            else:
                k = shown.index(sel) + step
                if 0 <= k < len(shown):
                    new = shown[k]
                elif self.busy():
                    JOURNAL.mark("XT bouton Channel %+d ignoré (fader tenu, changement de banque)" % step)
                    return True
                elif (kb := self.state.bank(self.page, step)) is None:
                    new = sel                     # tout au bout : on ne bouge pas
                else:
                    _, ent = self.state.layer_entries(self.page)
                    nxt = [e for e in (ent or []) if e is not None]
                    new = (nxt[0] if step > 0 else nxt[-1]) if nxt else sel
            self.state.selected = new
        JOURNAL.mark("XT bouton Channel %+d -> sélection %s" % (step, new))
        if self.lv1:
            if kb is not None:
                self.lv1.layer(kb)
            self.lv1.select(new)
        return True

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        if (status & 0xF0) == 0xB0 and d1 == CC_JOG:
            n = d2 & 0x0F
            notches = -n if d2 & 0x40 else n
            JOURNAL.mark("XT jog %+d" % notches)
            if self.lv1:
                self.lv1.jog(notches)
            elif self.transport and self.transport.reaper:
                self.transport.jog(notches)
            elif "jog" not in self.warned:
                print("  Jog wheel : réglage des plugins avec --clic-lv1 seulement.")
                self.warned.add("jog")
            return True
        if (status & 0xF0) == 0x90 and d1 == NOTE_FLIP:
            if d2:
                with self.state.lock:
                    keys = [k for k, (_s, func, on) in sorted(self.state.user_keys.items())
                            if on and "flip ab" in (func or "").lower()]
                if not keys:
                    JOURNAL.mark("XT bouton Flip : aucune User Key « Flip AB » dans la LV1")
                    if "flip" not in self.warned:
                        print("  FLIP : assigne une User Key de la LV1 à « Flip AB Input channel ».")
                        self.warned.add("flip")
                elif self.write:
                    self.link.send("/Set/UserKey", [("i", keys[0]), ("T", True)])
                    self.link.send("/Set/UserKey", [("i", keys[0]), ("F", False)])
                    JOURNAL.mark("XT bouton Flip -> User Key %d (Flip A/B)" % (keys[0] + 1))
            return True
        if (status & 0xF0) == 0x90 and d1 == NOTE_SMPTE:
            if d2:
                self.reaper_tc = not self.reaper_tc
                JOURNAL.mark("XT bouton SMPTE -> afficheur : %s" % ("timecode REAPER" if self.reaper_tc else "heure"))
            return True
        if (status & 0xF0) == 0x90 and d1 in (NOTE_INPUTS, NOTE_BUSES, NOTE_USER, NOTE_GROUP, NOTE_GLOBAL_VIEW):
            if d2:
                self.on_view(d1)
            return True
        if (status & 0xF0) == 0x90 and d1 == NOTE_SOLO_ALL:
            if d2:
                with self.state.lock:
                    for t_ in self.state.tracks.values():
                        t_["solo"] = False          # mise à jour locale (la LV1 confirme par /Notify/Solo)
                if self.write:
                    self.link.send("/ClearAllSolo", [])
                JOURNAL.mark("XT bouton Solo -> /ClearAllSolo")
            return True
        if (status & 0xF0) == 0x90 and d1 in (NOTE_BANK_LEFT, NOTE_BANK_RIGHT):
            return True if d2 == 0 else self.on_bank(d1)
        if (status & 0xF0) == 0x90 and d1 in (NOTE_CHANNEL_LEFT, NOTE_CHANNEL_RIGHT):
            return True if d2 == 0 else self.on_channel(d1, entries)
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
        if kind == "Select":
            # Sélection locale au pont (la LV1 n'a pas de commande de sélection, comme dans MyFOH).
            with self.state.lock:
                self.state.selected = (g, ch)
            JOURNAL.mark("sélection %s" % ((g, ch),))
            if self.lv1:
                self.lv1.select((g, ch))
            return True
        if kind == "Rec":
            if kind not in self.warned:          # (Rec est pris par GainControl quand il est actif)
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
        self.gesture = {}      # clé -> valeurs du geste en cours (ancienne valeur + valeurs envoyées)
        self.untouched_move = {}   # tranche -> instant du dernier mouvement SANS toucher détecté (ongle)
        # tranche, piste (ou None) -> clé réglée : (g, ch) = fader de piste, (g, ch, aux) = envoi, None = rien
        self.key_of = lambda strip, e: e
        # tranche -> True si le fader est en lecture seule (master sur LR, demande de Joseph : fader critique, sert au
        # monitoring ; toucher = rien n'est envoyé, le moteur garde la position LV1)
        self.readonly = lambda strip: False

    def touch_display(self, now):
        """Tranches à marquer « touchées » à l'écran : doigt posé, ou fader bougé SANS toucher (ongle) pendant ce geste ;
        pas la temporisation d'après relâchement (HOLD_AFTER), qui ne sert qu'aux garde-fous."""
        out = [s for s, v in self.touched.items() if v]
        out += [s for s, t in self.untouched_move.items() if now - t < NAIL_SHOW and s not in out]
        return sorted(out)

    def held(self, now):
        return {s for s in set(self.touched) | set(self.hold_until)
                if self.touched.get(s) or now < self.hold_until.get(s, 0)}

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        kind = status & 0xF0
        chan = status & 0x0F
        if kind == 0xE0 and surface.strip_of(unit, chan) is not None:   # fader bougé (pitch bend)
            strip = surface.strip_of(unit, chan)
            value = d1 | (d2 << 7)
            if self.readonly(strip):
                self.hold_until[strip] = t + HOLD_AFTER          # pour le rappel à l'écran
                JOURNAL.mark("XT fader %s = %d ignoré (lecture seule)" % (label_of(strip), value))
                return True
            # Garde-fou 1 : si la X-Touch envoie le toucher, un fader non touché ne compte pas tant que son moteur
            # vient de recevoir une commande (c'est le moteur qui bouge, pas la main). Moteur au repos : c'est un
            # geste sans toucher détecté (ongle, gant…, remarque de Joseph du 15/10) -> il compte, s'il s'écarte
            # vraiment de la dernière position connue.
            mv = surface.motor.get(strip)
            if self.seen_touch and not self.touched.get(strip):
                moving = strip in self.hold_until and t < self.hold_until[strip]
                last = surface.sent_fader.get(surface.addr(strip))
                if (mv and t - mv[1] < MOTOR_BUSY) or (not moving and last is not None
                                                       and abs(last - value) <= UNTOUCHED_MIN):
                    JOURNAL.mark("XT fader %s = %d ignoré (pas touché)" % (label_of(strip), value))
                    return True
            # Garde-fou 2 : valeur proche d'une commande moteur récente (venue de la LV1) = écho du moteur.
            if not self.touched.get(strip) and mv and abs(mv[0] - value) <= 160 and t - mv[1] < 1.5:
                JOURNAL.mark("XT fader %s = %d ignoré (écho moteur)" % (label_of(strip), value))
                return True
            # Valeur identique à la dernière connue pour ce fader : rien de nouveau (évite toute boucle d'écho).
            if surface.sent_fader.get(surface.addr(strip)) == value:
                self.hold_until[strip] = t + HOLD_AFTER
                return True
            self.hold_until[strip] = t + HOLD_AFTER
            if not self.touched.get(strip):
                self.untouched_move[strip] = t           # geste sans toucher détecté : point de toucher pendant qu'il bouge
            surface.note_position(strip, value)
            e = entries[strip] if strip < len(entries) else None
            key = self.key_of(strip, e)
            if key is not None:
                if key not in self.gesture:
                    with self.state.lock:
                        old = self.state.fader_of(key)
                    self.gesture[key] = {round(old, 1)} if old is not None else set()
                self.pending[strip] = (key, fader_to_db(value), value)
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
                if self.readonly(strip):                 # lecture seule : le moteur reprend la position LV1
                    surface.sent_fader.pop(surface.addr(strip), None)
            return True
        return False

    def flush(self, now):
        """Envoie à la LV1 les positions en attente (limité à une toutes les 20 ms par fader)."""
        held_now = self.held(now)
        for strip, (key, db, value) in list(self.pending.items()):
            if now - self.last_sent.get(strip, 0) < SEND_EVERY:
                continue
            with self.state.lock:
                changed = self.state.fader_of(key) != db
                self.state.set_fader(key, db)   # mise à jour locale optimiste
            if changed:
                self.gesture.setdefault(key, set()).add(round(db, 1))
            if changed and self.write:
                if len(key) == 3:               # envoi aux (mode SEND)
                    self.link.send("/Set/Aux/Send/Gain", [("i", key[0]), ("i", key[1]), ("i", key[2]),
                                                          ("d", float(db))])
                    JOURNAL.mark("-> LV1 /Set/Aux/Send/Gain %d %d %d %s" % (key + (db,)))
                else:
                    self.link.send("/Set/Track/Out/Gain", [("i", key[0]), ("i", key[1]), ("d", float(db))])
                    JOURNAL.mark("-> LV1 /Set/Track/Out/Gain %d %d %s" % (key + (db,)))
            self.last_sent[strip] = now
            if strip not in held_now:
                del self.pending[strip]
                vals = self.gesture.pop(key, set()) - {round(db, 1)}
                with self.state.lock:
                    self.state.stale[key] = (vals, now + STALE_FOR)
        with self.state.lock:
            self.state.held_tracks = {self.pending[s][0] for s in self.pending}
        return held_now


def build_frame(state, mixer_page, n_strips, overrides):
    """Calcule ce que chaque tranche doit afficher."""
    with state.lock:
        if not state.connected:
            top = ["LV1 ?"] + [""] * (n_strips - 1)
            bot = ["attente"] + [""] * (n_strips - 1)
            state.last_leds = ([False] * n_strips, [False] * n_strips, [False] * n_strips)
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
            left = state.meter(g, c, 0)
            right = state.meter(g, c, 1)
            vals = [v for v in (left, right) if v is not None]
            lvls.append(db_to_level(max(vals)) if vals else 0)
        state.last_leds = (mutes, solos, [e is not None and e == state.selected for e in entries])
        return top, bot, cols, lvls, fads, layer_name, entries


def diagonal_problems(state):
    """Diagonale B (ligne n de la grille Input B -> canal n du pilote) : canaux dont l'entrée B n'y est pas.
    Lignes = voies des entrées dans l'ordre (2 par canal stéréo) ; vérifiées jusqu'à la taille du pilote."""
    bad = []
    with state.lock:
        size, routing = state.driver_size, state.routing
        if not size or not routing:
            return None                    # inconnu (base illisible, pas encore lue)
        row = 0
        for (g, ch), t in sorted(state.tracks.items()):
            if g != 0:
                continue
            legs = 2 if t.get("stereo") else 1
            want = [r for r in range(row, row + legs) if r < size]
            play = routing.get(ch, {}).get("play", [])
            if want and play[:len(want)] != want:
                bad.append((t.get("name") or default_label(g, ch)).strip())
            row += legs
    return bad


def input_list(state):
    """Entrées de la LV1 dans l'ordre : [(canal, nom, (r, g, b) 0..255 ou None, stéréo, rec, play)] (synchro des
    pistes Reaper). rec / play : canaux du pilote SoundGrid de ce PC (0-based) à enregistrer / en lecture sur
    l'entrée B, lus dans la base LV1 (state.routing, relu toutes les 5 s)."""
    out = []
    with state.lock:
        routing = state.routing
        for (g, ch), t in sorted(state.tracks.items()):
            if g != 0 or not t.get("name"):
                continue
            rgb = t.get("rgb")
            rt = routing.get(ch, {})
            out.append((ch, t["name"].strip(), tuple(int(round(v * 255)) for v in rgb) if rgb else None,
                        bool(t.get("stereo")), rt.get("rec", []), rt.get("play", [])))
    return out


SCENE_DELAY = 0.2        # s : on attend un peu le nom de la scène (/Notify/Scene/Name) avant de la transmettre


def scene_relay(state, bridge, link, now, write=True):
    """Scènes : LV1 -> Reaper (marqueur / curseur) et Reaper -> LV1 (marqueur franchi en lecture = rappel)."""
    import reaper_scenes
    with state.lock:
        ready = [(i, t) for i, t in state.scene_events if now - t >= SCENE_DELAY]
        state.scene_events = [e for e in state.scene_events if now - e[1] < SCENE_DELAY]
        names = {i: state.scenes.get(i) for i, _t in ready}
        scenes = dict(state.scenes)
    for idx, _t in ready:
        JOURNAL.mark("scène LV1 rappelée : %d « %s »" % (idx, names[idx]))
        bridge.scene_recalled(idx, names[idx] or "Scene %d" % (idx + 1))
    while True:
        try:
            name = bridge.requests.get_nowait()
        except queue.Empty:
            break
        idx = reaper_scenes.scene_index(scenes, name)
        if idx is None:
            JOURNAL.mark("Reaper demande la scène « %s » : inconnue sur la LV1" % name)
        elif write:
            link.send("/Set/CurSceneIndex", [("i", idx)])
            JOURNAL.mark("-> LV1 /Set/CurSceneIndex %d (« %s », marqueur Reaper)" % (idx, name))


RECALL_HOLD = 0.5        # s : le rappel de pistes reste affiché après le relâchement du dernier fader
RECALL_EVERY = 0.05      # s : rafraîchissement du rappel (vumètres) pendant qu'il est affiché


def recall_payload(state, entries, sends, touched, xlink=None, gain=None):
    """Contenu du rappel de pistes (16 tranches + master) : nom, couleur, valeur et position du fader (ou de l'envoi
    en mode sends), vumètres L/R, mute, solo, sélection, pan, gain X32 et 48 V (côté réglé en stéréo)."""
    cells = []
    if sends.picking:      # choix de l'aux : l'overlay montre les aux de la page (faders = leurs masters), pas la couche
        with state.lock:
            page = state.aux_tracks[16 * sends.page:16 * sends.page + MASTER]
        entries = [(g, ch) for g, ch, _n in page] + [None] * (MASTER - len(page)) + list(entries[MASTER:MASTER + 1])
    with state.lock:
        aux = sends.aux
        sel = state.selected
        for idx, e in enumerate(list(entries[:MASTER]) + [entries[MASTER] if len(entries) > MASTER else None]):
            if e is None:
                cells.append(None)
                continue
            t = state.tracks.get(e, {})
            rgb = t.get("rgb")
            send_off = False
            pan_v = t.get("pan")
            if aux is not None and idx < MASTER:
                s = state.sends.get((e[0], e[1], aux), {})
                val, send_off, pan_v = s.get("fader"), s.get("on") is False, s.get("pan")
            else:
                val = t.get("fader")
            meters = [state.meter(e[0], e[1], k) for k in (0, 1)]
            meters = [m for m in meters if m is not None] or [None]
            name = (t.get("name") or default_label(*e)).strip()
            cells.append({"name": name[:12], "color": "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in rgb)
                          if rgb else None, "value": fader_text(val).strip() if val is not None else "?",
                          "pos": round(db_to_fader(val) / 16383.0, 4) if val is not None else None,
                          "meters": meters, "meter": max([m for m in meters if m is not None], default=None),
                          "mute": bool(t.get("mute")), "solo": bool(t.get("solo")), "sel": e == sel,
                          "send_off": send_off, "pan": pan_label(pan_v).strip() if pan_v is not None else None,
                          "pan_v": pan_v, "num": str(e[1] + 1) if e[0] == 0 else ""})
    for idx, c in enumerate(cells):                   # gain X32 / 48 V : hors verrou (lien x32-gain-recall)
        e = (list(entries[:MASTER]) + [entries[MASTER] if len(entries) > MASTER else None])[idx]
        if c is None or xlink is None or e is None:
            continue
        side = gain.side.get(e, 0) if gain else 0
        g = xlink.gain(e, side)
        if g is not None:
            c["gain"] = ("%s%+.1f" % ("LR"[side], g)) if len(xlink.preamps(e)) == 2 else "%+.1f" % g
            c["ph"] = xlink.phantom_on(e, side)
    info = sends.overlay_info() if aux is not None else (None,)
    curve = [[d, p] for d, p in _values.FADER_CURVE]          # le petit fader de l'écran suit la courbe calibrée
    return {"cells": cells, "touched": touched, "send": info[0], "curve": curve}   # aux : « FX 1 »…


SUITE_FILE = os.path.join(HERE, "suite.json")    # écrit par l'installeur Total Control for LV1 :
#                                                  {"reaper": chemin de reaper.exe, "gainrecall": chemin de Gain Recall}


def start_reaper_lv1():
    """Lance REAPER LV1 (REAPER portable de Total Control for LV1) s'il est installé et pas déjà ouvert (demande de Joseph du 16/10 :
    XTouch-LV1 lance aussi REAPER LV1). Le pont tourne en administrateur : REAPER est lancé par explorer.exe, donc
    avec les droits normaux de l'utilisateur (glisser-déposer depuis l'Explorateur possible)."""
    try:
        with open(SUITE_FILE, encoding="utf-8") as f:
            exe = json.load(f).get("reaper")
    except (OSError, ValueError):
        return
    if not exe or not os.path.exists(exe) or sys.platform != "win32":
        return
    import subprocess
    no_window = 0x08000000
    ps = ("(Get-Process reaper -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq '%s' }) -ne $null"
          % exe.replace("'", "''"))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=no_window).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    if "True" in out:
        print("  REAPER LV1 : déjà ouvert")
        return
    subprocess.Popen(["explorer.exe", exe], creationflags=no_window)
    print("  REAPER LV1 : lancé (%s)" % exe)


GR_EXE = "XM32_Gain_Recall_LV1.exe"
GR_RUN_KEY, GR_RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "XM32 Gain Recall LV1"


def find_gain_recall(here=HERE, suite_file=None, env=None, run_value=None):
    """Chemin de X/M32 Gain Recall, quelle que soit l'installation (demande de Joseph du 16/10 : lancement auto « sur
    toutes les options ») : suite.json de l'installeur, dossier voisin (pack), %LOCALAPPDATA%\\Programs, à côté du
    pont (zip), puis la clé « Lancer avec Windows » de Gain Recall. None si introuvable."""
    env = os.environ if env is None else env
    cands = []
    try:
        with open(suite_file or SUITE_FILE, encoding="utf-8") as f:
            cands.append(json.load(f).get("gainrecall"))
    except (OSError, ValueError):
        pass
    cands.append(os.path.join(os.path.dirname(here), "X32 Gain Recall", GR_EXE))
    if env.get("LOCALAPPDATA"):
        cands.append(os.path.join(env["LOCALAPPDATA"], "Programs", "X32 Gain Recall", GR_EXE))
    cands.append(os.path.join(here, GR_EXE))
    if run_value is None and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GR_RUN_KEY) as k:
                run_value = winreg.QueryValueEx(k, GR_RUN_NAME)[0]
        except OSError:
            run_value = None
    if run_value:
        cands.append(run_value.split('"')[1] if run_value.startswith('"') else run_value.split(" --")[0])
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def start_gain_recall():
    """Lance X/M32 Gain Recall s'il est trouvé et pas déjà ouvert (n'importe quelle copie : une 2e instance ouvrirait
    sa page dans le navigateur). Option --at-login de Gain Recall : pas de navigateur, float caché tant que la LV1
    n'est pas là. Lancé détaché : il continue si on ferme le pont (il hérite de ses droits administrateur)."""
    if sys.platform != "win32":
        return
    exe = find_gain_recall()
    if not exe:
        print("  X/M32 Gain Recall : introuvable, pas lancé (gain X32 sur TRACK indisponible)")
        return
    import subprocess
    no_window = 0x08000000
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % GR_EXE, "/NH"], capture_output=True, text=True,
                             timeout=15, creationflags=no_window).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    if GR_EXE.lower() in out.lower():
        print("  X/M32 Gain Recall : déjà ouvert")
        return
    subprocess.Popen([exe, "--at-login"], cwd=os.path.dirname(exe), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    print("  X/M32 Gain Recall : lancé (%s)" % exe)


def open_units(midi, a, wait=False):
    """Ouvre les sorties X-Touch / Extender : [(libellé, id SysEx, handle)] (Extender d'abord sauf --ext-droite), ou
    [] si aucune. wait : attendre le branchement USB (vérifié toutes les 2 s) ; None si « Quitter » pendant l'attente."""
    ports = midi.list()
    main_idx, ext_idx = X.pick_ports(ports, a.main, a.ext)
    if wait and main_idx is None and ext_idx is None:            # plug and play : on attend le branchement USB
        print("  En attente des X-Touch (brancher l'USB)...")
        while main_idx is None and ext_idx is None:
            if STOP.wait(2):
                return None
            ports = midi.list()
            main_idx, ext_idx = X.pick_ports(ports, a.main, a.ext)
        if STOP.wait(2):                                         # laisser Windows finir d'installer les deux ports
            return None
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
            JOURNAL.mark("sortie %s ouverte (port %d)" % (label, idx))
        except OSError as e:
            print("  %s : %s" % (label, e))
            JOURNAL.mark("sortie %s REFUSÉE : %s" % (label, e))
    # Par défaut l'Extender est à GAUCHE (installation de Joseph) : elle porte les tranches 1-8.
    if not a.ext_droite and len(units) == 2:
        units.reverse()
    return units


def open_inputs(midi_in, units):
    """Entrées MIDI : même ordre que les sorties (unité 0 = tranches 1-8). Renvoie le nombre d'entrées ouvertes :
    une entrée refusée (déjà ouverte par un autre programme, erreur 4) = boutons et faders muets (18/10 : trois
    lancements sans un seul appui reçu) -> la boucle réessaie (`ports_missing`)."""
    opened = 0
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
            opened += 1
            print("  %s : entrée %d « %s »" % (label, idx, dict(in_ports).get(idx, "?")))
            JOURNAL.mark("entrée %s ouverte (port %d)" % (label, idx))
        except OSError as e:
            print("  %s : %s" % (label, e))
            JOURNAL.mark("entrée %s REFUSÉE : %s" % (label, e))
    return opened


def ports_missing(midi, midi_in, a, wanted, units, inputs_open):
    """(quoi, raison) s'il faut rouvrir des ports, sinon (None, None) : "sorties" = une unité du démarrage manque (tout
    est rouvert), "entrées" = une entrée n'est pas ouverte (seules les entrées sont rouvertes : pas d'écrans renvoyés
    toutes les 3 s si un autre programme la garde). Seulement si le port est de nouveau listé par Windows."""
    have = [label for label, _, _ in units]
    out_ports = midi.list()
    main_idx, ext_idx = X.pick_ports(out_ports, a.main, a.ext)
    listed = {"X-Touch": main_idx is not None, "Extender": ext_idx is not None}
    lost = [w for w in wanted if w not in have and listed.get(w)]
    if lost:
        return "sorties", "unité revenue : %s" % ", ".join(lost)
    if midi_in is not None and inputs_open < len(units):
        in_main, in_ext = X.pick_ports(midi_in.list(), None, None)
        if any({"X-Touch": in_main, "Extender": in_ext}.get(label) is not None for label in have):
            return "entrées", "entrée MIDI pas ouverte (%d / %d)" % (inputs_open, len(units))
    return None, None


OVERLAY_FACTORY = None   # tests : fabrique d'un faux affichage d'écran (sinon Qt / tkinter hors --dry-run)
STOP = threading.Event()  # « Quitter » de l'icône près de l'horloge : fin propre de la boucle (écrans remis à zéro)


def redirect_output_to_log():
    """Exe sans fenêtre noire (Joseph, 16/10) : print() et les erreurs vont dans xtouch_console.txt, à côté de l'exe
    (remplacé à chaque lancement). Sans effet quand une console existe (py, tests)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        f = open(os.path.join(HERE, "xtouch_console.txt"), "w", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def already_running():
    """Une seule instance du pont (mutex Windows nommé) : sans fenêtre, un 2e lancement passerait inaperçu et se
    disputerait les ports MIDI avec le 1er. Le mutex reste tenu jusqu'à la fin du processus."""
    if sys.platform != "win32":
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    already_running.handle = k32.CreateMutexW(None, False, "Local\\XTouchLV1_Bridge")
    return k32.GetLastError() == 183                       # ERROR_ALREADY_EXISTS


RELEASES_API = "https://api.github.com/repos/thaleosguest/xtouch-lv1/releases/latest"
RELEASES_PAGE = "https://github.com/thaleosguest/xtouch-lv1/releases/latest"
UPDATE = {"version": None, "url": None}   # mise à jour disponible (avis de mise à jour, demande de Joseph du 18/10)


def version_tuple(text):
    """« v0.2.10 » -> (0, 2, 10) ; () si ce n'est pas un numéro de version."""
    parts = (text or "").strip().lstrip("vV").split(".")
    return tuple(int(x) for x in parts) if parts and all(x.isdigit() for x in parts) else ()


def check_update(tray_icon=None, fetch=None):
    """Dernière release publiée sur GitHub plus récente que VERSION -> UPDATE + bulle près de l'horloge (une fois par
    version). Rien n'est téléchargé : le menu de l'icône ouvre la page de téléchargement (comme X/M32 Gain Recall)."""
    try:
        if fetch is None:
            import urllib.request
            req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "XTouch-LV1/%s" % VERSION,
                                                                "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rel = json.loads(r.read())
        else:
            rel = fetch()
    except Exception as e:
        print("  Vérification des mises à jour impossible : %s" % e)
        return
    tag = rel.get("tag_name") or ""
    if rel.get("draft") or rel.get("prerelease") or not version_tuple(tag):
        return
    if version_tuple(tag) > version_tuple(VERSION):
        new = UPDATE["version"] != tag.lstrip("vV")
        UPDATE.update(version=tag.lstrip("vV"), url=rel.get("html_url") or RELEASES_PAGE)
        print("  Mise à jour disponible : %s (%s)" % (UPDATE["version"], UPDATE["url"]))
        JOURNAL.mark("mise à jour disponible : %s" % UPDATE["version"])
        if new and tray_icon:
            tray_icon.notify("Total Control for LV1 %s disponible" % UPDATE["version"],
                             "Clic droit sur l'icône XTouch-LV1 > Mise à jour, pour la télécharger.")


def update_loop(tray_icon):
    """Au lancement (après 10 s : la LV1 et les X-Touch d'abord), puis une fois par jour (pont laissé ouvert)."""
    if STOP.wait(10):
        return
    while True:
        check_update(tray_icon)
        if STOP.wait(24 * 3600):
            return


def start_tray():
    """Icône près de l'horloge (comme X/M32 Gain Recall) : mise à jour (si disponible), mode d'emploi, dossier des
    journaux, Quitter."""
    try:
        import tray
    except ImportError:
        return None

    def open_path(path):
        """Par explorer.exe : le pont est administrateur, le navigateur / le dossier s'ouvrent avec les droits normaux."""
        import subprocess
        try:
            subprocess.Popen(["explorer.exe", path], creationflags=0x08000000)
        except OSError:
            pass
    return tray.TrayIcon(
        "XTouch-LV1 v%s" % VERSION,
        [(lambda: ("Mise à jour %s disponible..." % UPDATE["version"]) if UPDATE["version"] else None,
          lambda: open_path(UPDATE["url"] or RELEASES_PAGE)),
         ("Mode d'emploi", lambda: open_path(os.path.join(HERE, "MODE_EMPLOI.html"))),
         ("Dossier des journaux", lambda: open_path(HERE)),
         None,
         ("Quitter XTouch-LV1", STOP.set)],
        icon_path=os.path.join(HERE, "assets", "icon.ico"),
    ).start()


def main():
    ap = argparse.ArgumentParser(description="LV1 sur X-Touch + Extender : affichage + faders (étape 1).")
    ap.add_argument("--mixer", choices=["auto", "1", "2"], default="auto",
                    help="Mixer suivi : auto = l'onglet / la fenêtre Mixer affiché (défaut), ou 1 / 2 imposé")
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
    ap.add_argument("--x32", default="http://127.0.0.1:8032",
                    help="adresse de X/M32 Gain Recall pour le gain / 48 V X32 ('aucun' pour désactiver)")
    ap.add_argument("--reaper", default=None,
                    help="Reaper OSC hôte:port d'envoi:port des retours (transport de la X-Touch) ; 'aucun' pour désactiver")
    ap.add_argument("--pilote", default=None,
                    help="pilote SoundGrid de Reaper (nom dans l'inventaire LV1, ex. TracksLive-FL) ; "
                         "défaut : celui du PC de la LV1")
    ap.add_argument("--dossier-reaper", default=None,
                    help="dossier d'échange avec les scripts Reaper (défaut : ./reaper ; Reaper sur un autre PC : "
                         "dossier partagé contenant aussi les scripts .lua, ex. //PC-REAPER/lv1)")
    ap.add_argument("--sans-cadre", action="store_true",
                    help="pas de bandeau ni de cadre rouge à l'écran du PC en mode sends")
    ap.add_argument("--jog-methode", choices=["message", "souris"], default="message",
                    help="jog wheel -> LV1 : message de molette à la fenêtre (défaut) ou pointeur déplacé un instant")
    ap.add_argument("--clic-lv1", action="store_true",
                    help="la LV1 suit BANK et la sélection par clics simulés (pont lancé en administrateur)")
    ap.add_argument("--master", default="3:0",
                    help="piste LV1 du fader master, groupe:canal (3:0 = LR, défaut ; 'aucun' pour désactiver)")
    ap.add_argument("--sans-reaper-lv1", action="store_true",
                    help="ne pas lancer REAPER LV1 (installé par Total Control for LV1) avec le pont")
    ap.add_argument("--sans-gain-recall", action="store_true",
                    help="ne pas lancer X/M32 Gain Recall avec le pont")
    ap.add_argument("--attendre", action="store_true",
                    help="attendre que les X-Touch soient branchées (défaut de l'exe compilé)")
    argv = sys.argv[1:]
    if getattr(sys, "frozen", False) and not argv:      # exe lancé d'un double-clic : réglage de Joseph
        argv = ["--clic-lv1", "--attendre"]
    a = ap.parse_args(argv)
    if getattr(sys, "frozen", False) and already_running():      # AVANT le journal de sortie : un 2e lancement
        return 0                                                 # écrasait xtouch_console.txt du 1er (18/10)
    redirect_output_to_log()
    tray_icon = start_tray() if (getattr(sys, "frozen", False) and not a.dry_run) else None
    if tray_icon:
        threading.Thread(target=update_loop, args=(tray_icon,), daemon=True).start()
    print("  XTouch-LV1 v%s" % VERSION)
    if not a.dry_run and not a.sans_reaper_lv1:
        threading.Thread(target=start_reaper_lv1, daemon=True).start()
    if not a.dry_run and not a.sans_gain_recall and a.x32.lower() not in ("aucun", "none", "off"):
        threading.Thread(target=start_gain_recall, daemon=True).start()

    if not a.no_journal:
        jpath = os.path.join(HERE, "xtouch_journal_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        JOURNAL.current = Journal(jpath)          # emplacement partagé avec bridge/ (étape 8a)
        print("  Journal des messages LV1 : %s" % jpath)

    if a.dry_run:
        midi = X.DryOut()
    elif sys.platform != "win32":
        print("Windows uniquement (ou --dry-run).")
        return 2
    else:
        midi = X.WinMidiOut()
    midi = SafeMidi(midi)

    units = open_units(midi, a, wait=a.attendre)
    if units is None:                                  # « Quitter » pendant l'attente des X-Touch
        if tray_icon:
            tray_icon.stop()
        return 0
    if not units:
        print("Aucune X-Touch utilisable. Liste des ports : py xtouch_probe.py --list")
        return 3

    events = EVENTS
    midi_in = None
    wanted = [label for label, _, _ in units]          # unités du démarrage : on les veut toutes après une coupure
    inputs_open = 0
    if not a.dry_run:
        midi_in = WinMidiIn(events)
        inputs_open = open_inputs(midi_in, units)
    ports_check = [time.time()]
    load_fader_curve()

    overrides = load_color_overrides()
    if overrides:
        print("  Couleurs personnalisées : %d entrées (xtouch_couleurs.json)" % len(overrides))

    state = LV1State()
    fixed_view = None if a.mixer == "auto" else int(a.mixer) - 1
    state.view = fixed_view or 0
    link = LV1Link(state, a.host, a.port)
    link.start()
    xt = Surface(midi, units)
    faders = FaderControl(state, link, write=not a.lecture_seule)
    buttons = ButtonControl(state, link, write=not a.lecture_seule, page=state.view,
                            busy=lambda: bool(faders.held(time.time())))
    xlink = None
    if a.x32.lower() not in ("aucun", "none", "off"):
        import xgr_link
        xlink = xgr_link.GainRecallLink(a.x32)
        xlink.start()
        print("  Gain X32 via X/M32 Gain Recall (%s) : TRACK = encodeurs sur le gain, Rec tenu 1 s = 48 V." % a.x32)
    gain = GainControl(state, xlink, write=not a.lecture_seule, lv1=link)
    sends = SendControl(state, link, write=not a.lecture_seule, gain=gain)
    reaper = None
    import reaper_link
    if a.reaper is None:                  # défaut : Reaper local ; rien en --dry-run (tests), sauf s'il est demandé
        a.reaper = "aucun" if a.dry_run else "127.0.0.1:8000:9000"
    target = reaper_link.parse_target(a.reaper)
    if target:
        reaper = reaper_link.ReaperLink(*target, journal=lambda m: JOURNAL.mark(m))
        print("  Reaper (OSC %s:%d, retours sur %d) : transport, marqueurs, zoom, jog hors plugin LV1." % target)
    transport = TransportControl(reaper)
    apps = AppControl(state, link, reaper, state.view + 1, write=not a.lecture_seule) if not a.dry_run else None
    scene_bridge = None
    if reaper:                       # scènes LV1 <-> marqueurs Reaper (script reaper/lv1_scenes.lua dans Reaper)
        import reaper_scenes
        scene_bridge = reaper_scenes.SceneBridge(folder=a.dossier_reaper, journal=lambda m: JOURNAL.mark(m))
        if not a.dry_run:
            def watch_routing():          # patch vers le pilote SoundGrid : la LV1 ne l'annonce pas, on relit la base
                last = None
                while True:
                    try:
                        import lv1_db
                        drv, rt = lv1_db.routing(driver=a.pilote)
                        size = lv1_db.driver_size(driver=a.pilote)
                        if rt != last:
                            last = rt
                            JOURNAL.mark("routage pilote %s : %s" % (drv, rt))
                        with state.lock:
                            state.routing = rt
                            state.driver_size = size
                    except Exception as e:
                        JOURNAL.mark("routage illisible : %r" % e)
                    time.sleep(5.0)
            threading.Thread(target=watch_routing, daemon=True).start()
        print("  Scènes LV1 <-> marqueurs Reaper : charger reaper/lv1_scenes.lua dans Reaper (Actions > Load ReaScript).")
    buttons.transport = transport
    overlay = OVERLAY_FACTORY(state.view + 1) if OVERLAY_FACTORY else None     # tests : faux affichage d'écran
    if overlay is None and not a.dry_run and not a.sans_cadre and sys.platform == "win32":
        import xtouch_overlay
        overlay = xtouch_overlay.make_overlay(state.view + 1)   # Qt (style Gain Recall v3) si PySide6, sinon tk
    faders.key_of = sends.key_of
    gain.send_aux = lambda: sends.aux
    # master en lecture seule quand il est sur LR (hors sends on fader : là, il règle le master de l'aux)
    faders.readonly = lambda strip: strip == MASTER and sends.aux_track() is None

    def load_pans(force=False):
        """Pans et envois des entrées (le réseau ne les donne pas) : copie de la base de la LV1. force : après un
        état complet (rappel de scène, Flip A/B), les valeurs de la base remplacent celles qu'on avait."""
        try:
            import lv1_db
            pans = lv1_db.input_pans()
        except Exception as e:                # base absente (autre PC, test) : « ? » jusqu'au 1er changement
            JOURNAL.mark("pans de départ illisibles : %r" % e)
            return
        with state.lock:
            now_ = time.time()
            for key, v in pans.items():
                t = state.track(*key)
                if t["pan"] is None or (force and now_ >= state.pan_hold.get(key, 0)):
                    t["pan"] = v
        JOURNAL.mark("pans de départ lus dans la base LV1 : %d entrées" % len(pans))
        try:
            snd = lv1_db.input_sends()
        except Exception as e:
            JOURNAL.mark("envois de départ illisibles : %r" % e)
            return
        with state.lock:
            for key, (g_db, on) in snd.items():
                s = state.send(*key)
                if s["fader"] is None or (force and key not in state.held_tracks):
                    s["fader"] = g_db
                if s["on"] is None or force:
                    s["on"] = on
        JOURNAL.mark("envois de départ lus dans la base LV1 : %d" % len(snd))
    ab_seen = [0.0]

    def load_ab():
        """LED FLIP : entrées sur B ? (la LV1 ne l'annonce pas ; elle renvoie tout son état à chaque Flip A/B)."""
        try:
            import lv1_db
            ab = lv1_db.input_ab()
        except Exception as e:
            JOURNAL.mark("A/B illisible : %r" % e)
            return
        n_b = sum(1 for v in ab.values() if v)
        with state.lock:
            state.on_b = n_b > 0
        JOURNAL.mark("entrées sur B : %d / %d" % (n_b, len(ab)))
    if not a.dry_run:
        link.on_connect = load_pans
        with state.lock:
            already = state.connected
        if already:                           # connectée avant ce branchement : on lit tout de suite
            threading.Thread(target=load_pans, daemon=True).start()
    if not a.dry_run:
        LayerModeWatcher(state, state.view).start()           # voyants INPUTS / BUSES / USER / GROUP
        if sys.platform == "win32":
            ViewFollower(state, fixed_view).start()           # Mixer suivi (onglet / fenêtre) + voyant GLOBAL VIEW
    if a.lecture_seule:
        print("  Mode lecture seule : rien n'est envoyé à la LV1.")
    if a.clic_lv1 and not a.lecture_seule:
        import lv1_clic
        if not lv1_clic.is_admin():
            print("  --clic-lv1 : PAS administrateur, Windows bloquera les clics (relancer en administrateur).")
        buttons.lv1 = LV1Clicker(state, state.view, jog_method=a.jog_methode)
        if reaper:
            buttons.lv1.jog_fallback = transport.jog
        buttons.lv1.start()
        LV1SelectionWatcher(state, state.view).start()
        print("  Clics LV1 : la LV1 suit BANK et la sélection, la X-Touch suit la sélection LV1 (Mixer suivi : %s)."
              % ("onglet affiché" if fixed_view is None else "Mixer %d" % (fixed_view + 1)))
    print("Recherche de la LV1… (Ctrl+C pour arrêter)")
    entries = [None] * xt.strips
    master_target = None
    if a.master.lower() not in ("aucun", "none", "off"):
        try:
            g_, c_ = (int(x) for x in a.master.split(":"))
            master_target = (g_, c_)
        except ValueError:
            print("  --master %r invalide (attendu groupe:canal, ex. 3:0) : master désactivé." % a.master)
    if master_target and xt.master_unit is not None:
        print("  Fader master -> %s" % default_label(*master_target))
    last_layer = object()
    last_toast = [None]                   # dernier (Mixer, nom) notifié (pas deux notifs pour la même couche)
    shown_view = [state.view]
    woke = []
    tracks_sent = [0.0]
    diag_t = [0.0, None]                    # message reçu pendant l'attente de fin de tour, traité au début du suivant
    recall_until, recall_sent, recall_touched = [0.0], [0.0], [None]
    t_end = time.time() + a.seconds if a.seconds else None
    try:
        while not (t_end and time.time() > t_end) and not STOP.is_set():
            if not midi.lost and time.time() - ports_check[0] > 3.0 and not a.dry_run:
                ports_check[0] = time.time()
                what, why_missing = ports_missing(midi, midi_in, a, wanted, units, inputs_open)
                if what == "sorties":
                    midi.lost = why_missing
                elif what == "entrées":
                    JOURNAL.mark("nouvel essai des entrées MIDI : %s" % why_missing)
                    midi_in.close_all()
                    inputs_open = open_inputs(midi_in, units)
            if midi.lost:                                # X-Touch disparue : on attend qu'elle revienne, puis on rouvre
                print("  X-Touch perdue (%s) : en attente de son retour..." % midi.lost)
                JOURNAL.mark("X-Touch perdue : %s" % midi.lost)
                for _, _, h in units:
                    midi.close(h)
                if midi_in:
                    midi_in.close_all()
                again = None if STOP.wait(1) else open_units(midi, a, wait=True)   # pas de boucle folle
                t_all = time.time() + 20                 # 18/10 : reconnectée avec 1 unité sur 2 -> attendre les deux
                while again is not None and len(again) < len(wanted) and time.time() < t_all:
                    for _, _, h in again:
                        midi.close(h)
                    again = None if STOP.wait(2) else open_units(midi, a, wait=True)
                if again is None:
                    units = []
                    break
                units[:] = again
                midi.lost = None
                inputs_open = open_inputs(midi_in, units) if (midi_in and units) else 0
                ports_check[0] = time.time()
                xt = Surface(midi, units)           # caches vides : tout est renvoyé (écrans, LED, moteurs)
                JOURNAL.mark("X-Touch reconnectée (%d unité(s))" % len(units))
                print("  X-Touch reconnectée.")
                if not units:
                    continue
            now = time.time()
            while True:
                if woke:
                    unit, st, d1, d2, t = woke.pop()
                else:
                    try:
                        unit, st, d1, d2, t = events.get_nowait()
                    except queue.Empty:
                        break
                if not (faders.on_midi(unit, st, d1, d2, t, entries, xt)
                        or sends.on_midi(unit, st, d1, d2, t, entries, xt)
                        or gain.on_midi(unit, st, d1, d2, t, entries, xt)
                        or transport.on_midi(unit, st, d1, d2, t, entries, xt)
                        or (apps is not None and apps.on_midi(unit, st, d1, d2, t, entries, xt))
                        or buttons.on_midi(unit, st, d1, d2, t, entries, xt)):
                    JOURNAL.mark("MIDI unité %d : %02X %02X %02X" % (unit, st, d1, d2))
            held = faders.flush(now)
            view = state.view
            if view != shown_view[0]:                       # autre Mixer : overlay (fenêtre détachée) et bascule d'appli
                shown_view[0] = view
                if overlay and hasattr(overlay, "set_mixer"):
                    overlay.set_mixer(view + 1)
                if apps is not None:
                    apps.mixer = view + 1
            top, bot, cols, lvls, fads, layer_name, entries = build_frame(state, view, xt.strips, overrides)
            send_leds = sends.frame(entries, top, bot, cols, fads, overrides)
            master_now = sends.aux_track() or master_target      # mode SEND : fader master = master de l'aux
            entries = list(entries) + [None] * (MASTER - len(entries)) + [master_now]
            master_fv = None
            if master_now:
                with state.lock:
                    connected = state.connected
                    mdb = state.tracks.get(master_now, {}).get("fader")
                master_fv = db_to_fader(mdb) if connected and mdb is not None else None
            if layer_name != last_layer:
                if layer_name:
                    print("  Couche affichée : %s" % layer_name)
                    JOURNAL.mark("affiché : %s" % layer_name)
                    toast = layer_toast(layer_name)
                    if overlay and toast and (view, toast) != last_toast[0]:   # banque X-Touch puis LV1 : une notif
                        last_toast[0] = (view, toast)                          # (re-notifiée en changeant de Mixer)
                        overlay.set_layer(toast)
                last_layer = layer_name
            rings, recs = gain.frame(entries[:xt.strips], bot)
            xt.push(top, bot, cols, lvls, fads, now, held, master_fv)
            xt.push_leds(*send_leds, recs=recs)
            xt.push_rings(rings)
            xt.set_main_led(NOTE_TRACK, gain.mode)
            xt.set_main_led(NOTE_PAN, gain.pan_mode)
            xt.set_main_led(NOTE_SEND, sends.aux is not None or (sends.picking and int(now * 3) % 2 == 0))
            if scene_bridge:
                scene_relay(state, scene_bridge, link, now, write=not a.lecture_seule)
                if now - tracks_sent[0] >= 1.0:                  # liste des entrées pour la synchro des pistes Reaper
                    tracks_sent[0] = now
                    scene_bridge.write_tracks(input_list(state))
            if apps is not None:
                xt.set_main_led(NOTE_DISPLAY, apps.front == "reaper")      # LED DISPLAY = Reaper devant
            if reaper:
                for note, on in transport.leds().items():
                    xt.set_main_led(note, on)
            for k, on in enumerate(sends.fkey_leds()):
                xt.set_main_led(NOTE_F1 + k, on)
            with state.lock:
                lmode, ltab, lspill = state.layer_mode.get(state.view), state.lv1_tab, state.spill_lit
            for note, on in view_leds(lmode, ltab, lspill).items():       # touches View = mode de couche / onglet All
                xt.set_main_led(note, on)
            xt.set_main_led(NOTE_SMPTE, buttons.reaper_tc)   # SMPTE : timecode choisi ; LED SMPTE : affiché
            xt.set_main_led(NOTE_LED_SMPTE, bool(buttons.reaper_tc and reaper and reaper.alive()))
            with state.lock:
                sel = state.selected
                any_solo = any(t.get("solo") for t in state.tracks.values())
                lr_db = state.tracks.get(master_now, {}).get("fader") if master_now else None
            if sends.picking:                                # choix de l'aux : « SE » + « SEL »
                assign = seg_codes("SE", 2)
                timecode = seg_codes("SEL", 5) + seg_codes("", 5)
            elif sends.aux is not None:                      # envois : « SE » + aux + niveau du master de l'aux
                side = gain.side.get(sel, 0)
                g_sel = xlink.gain(sel, side) if (xlink and sel) else None
                stereo = bool(xlink and sel and len(xlink.preamps(sel)) == 2)
                assign, timecode = master_display(sel, g_sel, side, stereo, lr_db)
                assign = seg_codes("SE", 2)
                timecode = seg_codes(sends.label() or "--", 5) + timecode[5:]
            else:                                            # position de REAPER LV1, sinon heure (Joseph, 16/10)
                tc = reaper.time if (buttons.reaper_tc and reaper and reaper.alive()) else None
                assign, timecode = time_display(tc, time.localtime())
            xt.push_master_display(assign, timecode)
            if overlay:
                if faders.held(now):                       # touché, ou bougé sans toucher (ongle) : bandeau affiché
                    recall_until[0] = now + RECALL_HOLD
                # point / contour de toucher : le doigt SEULEMENT (disparaît au relâchement, demande de Joseph du
                # 15/10), ou un geste sans toucher détecté (ongle) tant qu'il bouge
                touched = faders.touch_display(now)
                if now < recall_until[0]:
                    if now - recall_sent[0] >= RECALL_EVERY or touched != recall_touched[0]:
                        recall_sent[0], recall_touched[0] = now, touched
                        overlay.set_recall(recall_payload(state, entries, sends, touched, xlink, gain))
                elif recall_sent[0]:
                    recall_sent[0] = 0.0
                    overlay.set_recall(None)
                overlay.set_info(*sends.overlay_info())
                with state.lock:
                    fk = [k for k, (_s, func, on) in sorted(state.user_keys.items())
                          if on and "flip ab" in (func or "").lower()]
                    ab_now = state.on_b         # lu ici : on_b n'est défini que plus bas dans la boucle (bug du 15/10)
                overlay.set_ab(None if ab_now is None else ("B" if ab_now else "A"), fk[0] if fk else None)
                if now - diag_t[0] >= 1.0:                   # diagonale B cassée ? (patch relu toutes les 5 s)
                    diag_t[0] = now
                    bad = diagonal_problems(state)
                    warn = ("B PATCH\n%d OFF" % len(bad)) if bad else None
                    if warn != diag_t[1]:
                        diag_t[1] = warn
                        overlay.set_warn(warn)
                        if bad:
                            print("  Diagonale B cassée (%d canaux : %s) : page Patch > Input B, puis ENTER."
                                  % (len(bad), ", ".join(bad[:5]) + ("…" if len(bad) > 5 else "")))
                            JOURNAL.mark("diagonale B cassée : %s" % bad)
            xt.set_main_led(NOTE_RUDE_SOLO, any_solo and int(now * 2) % 2 == 0)   # clignote si un solo
            xt.set_main_led(NOTE_SOLO_ALL, any_solo)                                # SOLO : allumé si un solo
            with state.lock:
                on_b, ch_at = state.on_b, state.channels_at
            xt.set_main_led(NOTE_FLIP, bool(on_b))                                  # FLIP : entrées sur B
            if ch_at != ab_seen[0] and now - ch_at > 1.0 and not a.dry_run:              # état renvoyé (Flip A/B…)
                ab_seen[0] = ch_at
                def reload_all():
                    load_ab()
                    load_pans(force=True)      # rappel de scène : pans et envois rechargés (non vérifié)
                threading.Thread(target=reload_all, daemon=True).start()
            # Attente : réveil DÈS qu'un message X-Touch arrive (plus de sommeil fixe de 50 ms). L'écho d'un fader
            # bougé part ainsi en ~1 ms : moins de résistance du moteur quand le toucher n'est pas détecté (ongle)
            # ou en retard (geste très rapide) — remarque de Joseph du 15/10.
            try:
                woke.append(events.get(timeout=0.01 if faders.pending else TICK))
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        link.stop_flag = True
        if overlay:
            overlay.stop()
        if midi_in:
            midi_in.close_all()
        xt.clear()
        for _, _, h in units:
            midi.close(h)
        print("\nArrêté, écrans remis à zéro.")
        if tray_icon:
            tray_icon.stop()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--overlay":     # exe compilé : processus de l'overlay Qt
        del sys.argv[1]
        import xtouch_overlay_qt
        sys.exit(xtouch_overlay_qt.main())
    sys.exit(main())
