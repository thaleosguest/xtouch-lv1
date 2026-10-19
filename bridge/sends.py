"""Touche SEND : faders et encodeurs sur les envois aux (Fx / Mon) de la LV1, touche FLIP (User Key « Flip Sends »).

Déplacé de `xtouch_lv1_display.py` (étape 8d du refactor, 19/10/2026)."""
import time

from bridge.journal import JOURNAL
from bridge.values import FADER_MIN_DB, LV1_PAN_SCALE, db_to_fader
from surface.display import fader_text, rgb_to_xtouch
from surface.notes import (CC_VPOT, MASTER, NOTE_BANK_LEFT, NOTE_BANK_RIGHT, NOTE_F1, NOTE_MUTE, NOTE_SELECT,
                           NOTE_SEND, NOTE_VPOT_PUSH, XT)


def flip_target(func, aux_tracks):
    """Fonction de User Key « Flip Sends: MX1: Mon 1 » -> index de l'aux (ordre /Aux/Tracks), sinon None."""
    if not func or not func.lower().startswith("flip sends"):
        return None
    name = func.split(":")[-1].strip().lower()
    for k, (_g, _ch, n) in enumerate(aux_tracks):
        if n.strip().lower() == name:
            return k
    return None


# Le négatif (couleur + 0x20) n'a AUCUN effet en mode Mackie (essai de Joseph, 15/10) : à la place, la ligne du
# bas affiche l'aux devant le niveau d'envoi.


def send_label(short, db):
    """Ligne du bas en mode sends (7 car.) : « F1 -12 », « M12 -6 », « F3 -inf », « F1 ? »."""
    if db is None:
        lvl = "?"
    elif db <= FADER_MIN_DB:
        lvl = "-inf"
    else:
        room = 7 - len(short) - 1
        lvl = "%.1f" % db
        if len(lvl) > room:
            lvl = "%.0f" % db
    return ("%s %s" % (short, lvl))[:7]


def aux_short(track, aux):
    """Libellé court d'un aux pour l'afficheur : « F3 », « M12 ». track = (groupe, canal, nom) de /Aux/Tracks ;
    tiré du groupe et du canal, PAS du nom (journal du 15/10 : Fx 1 renommé « Reverb Hall » s'affichait « M1 »)."""
    if not track:
        return "A%d" % (aux + 1)
    return ("F" if track[0] == 2 else "M") + str(track[1] + 1)


class SendControl:
    """« Sends on fader » (demande de Joseph, 15/10/2026) : SEND -> les écrans listent les aux (Fx 1-8 sur les
    tranches 1-8, Mon 1-8 sur 9-16, BANK = Mon 9-16), Select choisit l'aux ; les faders règlent alors les envois de
    chaque canal vers lui (/Set/Aux/Send/Gain), Mute = envoi on/off (LED allumée = envoi coupé), encodeur = pan de
    l'envoi (s'il est connu ; appui = centre), fader master = master de l'aux. SEND à nouveau : retour normal.
    Pendant le choix de l'aux, les faders règlent les masters des aux ; les boutons de tranche sont bloqués."""
    PAN_STEP = 3.0 / 45.0
    PAN_HOLD = 0.5
    SOF_SETTLE = 0.15     # s sans changement d'InternalAssign avant de suivre (états de passage de la LV1)

    def __init__(self, state, link, write=True, gain=None):
        self.state, self.link, self.write = state, link, write
        self.gain = gain                  # GainControl : en mode TRACK / PAN, les encodeurs restent à lui
        self.aux = None                   # index aux réglé, ou None
        self.picking = False
        self.flip_key = None              # User Key (0..7) qui a mis la LV1 en Flip Sends (touches F1..F8)
        self.page = 0                     # choix : 0 = aux 0..15, 1 = aux 16..31
        self.lv1_sof = "?"                # dernier bus « sur les faders » de la LV1 déjà suivi (les 2 Mixers)

    def key_of(self, strip, e):
        """Clé réglée par un fader (branchée sur FaderControl.key_of). Pendant le choix de l'aux, les faders
        règlent les masters des aux affichés (remarque de Joseph : bloqués, ils revenaient en place)."""
        if self.picking:
            if strip == MASTER:
                return e
            k = 16 * self.page + strip
            with self.state.lock:
                aux = self.state.aux_tracks
                return (aux[k][0], aux[k][1]) if k < len(aux) else None
        if e is None:
            return None
        if self.aux is not None and strip != MASTER:
            return (e[0], e[1], self.aux)
        return e

    def aux_track(self):
        with self.state.lock:
            aux = self.state.aux_tracks
            if self.aux is not None and self.aux < len(aux):
                return (aux[self.aux][0], aux[self.aux][1])
        return None

    def overlay_info(self):
        """(texte, sous-titre, couleur #rrggbb) du bandeau / cadre à l'écran du PC, ou (None,) hors mode sends.
        Textes en anglais (demande de Joseph)."""
        if self.picking:
            return ("SELECT AN AUX", None, None)
        if self.aux is None:
            return (None,)
        with self.state.lock:
            aux = self.state.aux_tracks
            if self.aux >= len(aux):
                return (None,)
            g, ch, name = aux[self.aux]
            t = self.state.tracks.get((g, ch), {})
        track_name, rgb = t.get("name"), t.get("rgb")
        sub = track_name.strip() if track_name and track_name.strip().lower() != name.lower() else None
        color = "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in rgb) if rgb else None
        return (name.upper(), sub, color)

    def label(self):
        with self.state.lock:
            aux = self.state.aux_tracks
            track = aux[self.aux] if self.aux is not None and self.aux < len(aux) else None
        return aux_short(track, self.aux) if self.aux is not None else None

    def press_user_key(self, k):
        """Appui momentané sur la User Key k de la LV1 (T puis F, comme MyFOH / module Companion)."""
        if self.write:
            self.link.send("/Set/UserKey", [("i", k), ("T", True)])
            self.link.send("/Set/UserKey", [("i", k), ("F", False)])
        JOURNAL.mark("-> LV1 User Key %d" % (k + 1))

    def leave(self):
        """Sortie du mode sends ; si la LV1 y a été mise par une User Key Flip Sends, on la ramène aussi."""
        if self.flip_key is not None:
            self.press_user_key(self.flip_key)
            self.flip_key = None
        self.picking, self.aux = False, None

    def on_fkey(self, k):
        """F1..F8 (demande de Joseph, 15/10) : User Key k+1 de la LV1. Si elle est assignée à un Flip Sends, la
        X-Touch passe aussi en sends on fader vers cet aux ; un 2e appui ramène LV1 et X-Touch en mode normal."""
        with self.state.lock:
            _short, func, assigned = self.state.user_keys.get(k, ("", "", False))
            target = flip_target(func, self.state.aux_tracks) if assigned else None
        if target is None:
            self.press_user_key(k)
            JOURNAL.mark("XT F%d -> User Key %d (%s)" % (k + 1, k + 1, func or "non assignée"))
            return
        if self.flip_key == k:                       # même touche : retour au mode normal
            self.leave()
            JOURNAL.mark("XT F%d -> fin du Flip Sends" % (k + 1))
            return
        self.leave()                                 # autre mode sends en cours : on en sort proprement
        self.press_user_key(k)
        self.flip_key, self.aux, self.picking = k, target, False
        JOURNAL.mark("XT F%d -> Flip Sends vers l'aux %d (%s)" % (k + 1, target, self.label()))

    def follow_lv1(self, now, busy=False):
        """Sends on Fader activé / coupé SUR LA LV1 (menu Fx / Mon, User Key appuyée à l'écran), demande de Joseph du
        19/10 : la X-Touch et le bandeau à l'écran suivent. Seulement sur un CHANGEMENT de la LV1, stable depuis
        SOF_SETTLE : un Flip lancé par la X-Touch arrive au même état (rien à faire), le mode SEND local de la X-Touch
        (la LV1 reste sur LR) n'est pas touché. Jamais d'appui de User Key ici (il rebasculerait la LV1).
        busy (fader sous le doigt) : attendre le lâcher, comme le changement de Mixer."""
        with self.state.lock:
            bus = self.state.sof
            if bus == "?" or now - self.state.sof_t < self.SOF_SETTLE:
                return
            aux = self.state.aux_tracks
            keys = dict(self.state.user_keys)
        if bus == self.lv1_sof or busy:
            return
        target = next((k for k, (g, ch, _n) in enumerate(aux) if (g, ch) == bus), None)
        # InternalAssign suit en fait le SOLO (capture MyFOH du 19/10 : /Set/Solo d'une entrée -> InternalAssign 0 n) ;
        # un Flip Sends met l'aux en solo. Seuls comptent : un aux (sends) et LR (rien en solo : normal). Une entrée,
        # un groupe… en solo pendant les sends : ignoré (sinon la X-Touch sortait des sends à chaque Solo).
        if target is None and bus != (3, 0):
            return
        self.lv1_sof = bus
        if target is None:                       # LR : mode normal
            if self.aux is not None:
                JOURNAL.mark("LV1 : fin du Sends on Fader -> X-Touch en mode normal")
                self.flip_key, self.aux, self.picking = None, None, False
            return
        if target == self.aux and not self.picking:
            return
        self.flip_key = next((k for k in range(8) if keys.get(k, (None, None, False))[2]
                              and flip_target(keys[k][1], aux) == target), None)
        self.aux, self.picking = target, False
        JOURNAL.mark("LV1 : Sends on Fader vers l'aux %d (%s) -> X-Touch en sends%s"
                     % (target, self.label(), " (F%d)" % (self.flip_key + 1) if self.flip_key is not None else ""))

    def fkey_leds(self):
        """LED des touches F1..F8 : allumée = son Flip Sends est actif."""
        return [self.flip_key == k and self.aux is not None for k in range(8)]

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        kind = status & 0xF0
        if kind == 0x90 and NOTE_F1 <= d1 < NOTE_F1 + 8:
            if d2:
                self.on_fkey(d1 - NOTE_F1)
            return True
        if kind == 0x90 and d1 == NOTE_SEND:
            if d2:
                if self.picking or self.aux is not None:
                    self.leave()
                    JOURNAL.mark("XT bouton Send -> retour aux faders des canaux")
                else:
                    self.picking, self.page = True, 0
                    JOURNAL.mark("XT bouton Send -> choix de l'aux")
            return True
        if self.picking:
            if kind == 0x90 and d1 in (NOTE_BANK_LEFT, NOTE_BANK_RIGHT):
                if d2:
                    with self.state.lock:
                        n = len(self.state.aux_tracks)
                    self.page = max(0, min((n - 1) // 16 if n else 0, self.page + (1 if d1 == NOTE_BANK_RIGHT else -1)))
                return True
            if kind == 0x90 and NOTE_SELECT <= d1 < NOTE_SELECT + 8:
                if d2:
                    idx = 16 * self.page + 8 * unit + (d1 - NOTE_SELECT)
                    with self.state.lock:
                        n = len(self.state.aux_tracks)
                    if idx < n:
                        self.aux, self.picking, self.flip_key = idx, False, None
                        JOURNAL.mark("XT Select -> sends vers l'aux %d (%s)" % (idx, self.label()))
                return True
            if kind == 0x90 and d1 <= 0x1F:          # Rec / Solo / Mute bloqués pendant le choix
                return True
            if kind == 0x90 and NOTE_VPOT_PUSH <= d1 < NOTE_VPOT_PUSH + 8:
                return True
            if kind == 0xB0 and CC_VPOT <= d1 < CC_VPOT + 8:
                return True
            return False
        if self.aux is None:
            return False
        if kind == 0x90 and NOTE_MUTE <= d1 < NOTE_MUTE + 8:
            strip = 8 * unit + (d1 - NOTE_MUTE)
            e = entries[strip] if strip < len(entries) else None
            if d2 and e is not None:
                key = (e[0], e[1], self.aux)
                with self.state.lock:
                    s = self.state.send(*key)
                    new = not bool(s["on"])
                    s["on"] = new
                if self.write:
                    self.link.send("/Set/Aux/Send/On", [("i", key[0]), ("i", key[1]), ("i", key[2]),
                                                        ("T" if new else "F", new)])
                JOURNAL.mark("XT Mute tranche %d -> envoi %s %s" % (strip + 1, key, "ON" if new else "OFF"))
            return True
        # En sends on fader, les encodeurs règlent le pan de l'ENVOI, PAN allumé ou non (journal 184559 : PAN allumé,
        # ils réglaient le pan du canal). Seul TRACK (gain X32, ou trim LV1) les garde.
        busy = self.gain is not None and (self.gain.mode or self.gain.trim_mode)
        if not busy and kind == 0x90 and NOTE_VPOT_PUSH <= d1 < NOTE_VPOT_PUSH + 8:
            strip = 8 * unit + (d1 - NOTE_VPOT_PUSH)
            e = entries[strip] if strip < len(entries) else None
            if d2 and e is not None:
                self._set_pan((e[0], e[1], self.aux), 0.0)
            return True
        if not busy and kind == 0xB0 and CC_VPOT <= d1 < CC_VPOT + 8:
            strip = 8 * unit + (d1 - CC_VPOT)
            n = d2 & 0x0F
            delta = -n if d2 & 0x40 else n
            e = entries[strip] if strip < len(entries) else None
            if e is None or not delta:
                return True
            key = (e[0], e[1], self.aux)
            with self.state.lock:
                cur = self.state.sends.get(key, {}).get("pan")
            if cur is not None:
                self._set_pan(key, max(-1.0, min(1.0, round((cur + delta * self.PAN_STEP) * 45) / 45.0)))
            return True
        return False

    def _set_pan(self, key, value):
        with self.state.lock:
            self.state.send(*key)["pan"] = value
            self.state.pan_hold[key] = time.time() + self.PAN_HOLD
        if self.write:
            self.link.send("/Set/Aux/Send/Pan", [("i", key[0]), ("i", key[1]), ("i", key[2]),
                                                  ("d", value * LV1_PAN_SCALE)])
        JOURNAL.mark("XT encodeur -> pan envoi %s %+.3f" % (key, value))

    def frame(self, entries, top, bot, cols, fads, overrides):
        """Modifie l'affichage (choix de l'aux, ou niveaux d'envoi) ; renvoie les LED (mute, solo, select)."""
        n = len(top)
        with self.state.lock:
            mutes, solos, selects = (list(x) for x in self.state.last_leds[:3])
            if self.picking:
                aux = self.state.aux_tracks
                for i in range(n):
                    k = 16 * self.page + i
                    if k < len(aux):
                        g, ch, name = aux[k]
                        t = self.state.tracks.get((g, ch), {})
                        top[i], bot[i] = name[:7], fader_text(t.get("fader"))
                        cols[i] = rgb_to_xtouch(t.get("rgb")) if t.get("rgb") else XT["blanc"]
                        fads[i] = db_to_fader(t.get("fader"))
                    else:
                        top[i], bot[i], cols[i], fads[i] = "", "", XT["vide"], 0
                    mutes[i] = solos[i] = selects[i] = False
            elif self.aux is not None:
                aux = self.state.aux_tracks
                short = aux_short(aux[self.aux] if self.aux < len(aux) else None, self.aux)
                for i, e in enumerate(entries[:n]):
                    if e is None:
                        continue
                    s = self.state.sends.get((e[0], e[1], self.aux), {})
                    f = s.get("fader")
                    bot[i] = send_label(short, f)            # « F1 -12 » : on voit qu'on est en sends
                    fads[i] = db_to_fader(f)
                    mutes[i] = s.get("on") is False
        return mutes, solos, selects
