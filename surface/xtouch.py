"""Envoi vers la X-Touch (+ Extender) : écrans, couleurs, moteurs, vumètres, LED, couronnes, 7 segments.

Chaque valeur envoyée est gardée : on ne renvoie que ce qui change (sauf le vumètre, renvoyé toutes les
METER_REFRESH s). Déplacé tel quel de `xtouch_lv1_display.py` (étape 6 du refactor, 19/10/2026) ; seule
différence : le journal des moteurs passe par `motor_note`, que le pont redéfinit (même texte qu'avant).
"""
import xtouch_probe as X
from surface.notes import (MASTER, NOTE_REC, NOTE_SOLO, NOTE_MUTE, NOTE_SELECT, NOTE_TRACK, NOTE_PAN,
                           NOTE_RUDE_SOLO, NOTE_SEND, NOTE_SOLO_ALL, NOTE_FLIP, NOTE_INPUTS, NOTE_BUSES, NOTE_USER,
                           NOTE_GROUP, NOTE_GLOBAL_VIEW, NOTE_SMPTE, NOTE_LED_SMPTE, NOTE_F1, CC_TIMECODE,
                           CC_ASSIGN_L, CC_ASSIGN_R)

METER_REFRESH = 0.25    # renvoi d'un niveau inchangé (le vumètre retombe tout seul sinon)
FADER_TOL = 48          # écart (sur 16383) en dessous duquel on ne bouge pas le moteur


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
        self.sent_ring = {}    # (unité, encodeur) -> valeur de couronne
        self.sent_seg = {}     # CC de l'afficheur 7 segments -> code envoyé
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

    def push_leds(self, mutes, solos, selects=(), recs=()):
        selects = list(selects) + [False] * (len(mutes) - len(selects))
        recs = list(recs) + [False] * (len(mutes) - len(recs))
        for i, (m, so, se, r) in enumerate(zip(mutes, solos, selects, recs)):
            u, s = i // 8, i % 8
            self.set_led(u, NOTE_MUTE + s, bool(m))
            self.set_led(u, NOTE_SOLO + s, bool(so))
            self.set_led(u, NOTE_REC + s, bool(r))
            self.set_led(u, NOTE_SELECT + s, bool(se))

    def push_rings(self, values):
        """Couronnes de LED des encodeurs : CC 0x30+n, valeur Mackie (mode << 4) | position 0..11."""
        for i, v in enumerate(values):
            u, s = i // 8, i % 8
            if u < len(self.units) and self.sent_ring.get((u, s)) != v:
                self.midi.short(self.units[u][2], 0xB0, 0x30 + s, v)
                self.sent_ring[(u, s)] = v

    def push_master_display(self, assign, timecode):
        """Afficheur 7 segments : assign = 2 codes (gauche, droite), timecode = 10 codes (gauche -> droite)."""
        if self.master_unit is None:
            return
        h = self.units[self.master_unit][2]
        for cc, v in ((CC_ASSIGN_L, assign[0]), (CC_ASSIGN_R, assign[1])):
            if self.sent_seg.get(cc) != v:
                self.midi.short(h, 0xB0, cc, v)
                self.sent_seg[cc] = v
        for k, v in enumerate(timecode):
            cc = CC_TIMECODE + (len(timecode) - 1 - k)
            if self.sent_seg.get(cc) != v:
                self.midi.short(h, 0xB0, cc, v)
                self.sent_seg[cc] = v

    def set_main_led(self, note, on):
        """LED d'un bouton de la X-Touch principale (TRACK…)."""
        if self.master_unit is not None:
            self.set_led(self.master_unit, note, on)

    def motor_note(self, what, value):
        """Commande moteur envoyée (what = « master » / « tranche 3 ») : rien ici, le pont l'écrit dans son journal."""

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
                self.motor_note("master", master_fv)
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
                    self.motor_note("tranche %d" % (8 * u + s + 1), fv)
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
                    self.midi.short(h, 0xB0, 0x30 + s, 0)
                if u == self.master_unit:
                    self.midi.short(h, 0x90, NOTE_TRACK, 0)
                    self.midi.short(h, 0x90, NOTE_PAN, 0)
                    self.midi.short(h, 0x90, NOTE_RUDE_SOLO, 0)
                    self.midi.short(h, 0x90, NOTE_SEND, 0)
                    self.midi.short(h, 0x90, NOTE_SOLO_ALL, 0)
                    self.midi.short(h, 0x90, NOTE_FLIP, 0)
                    for note in (NOTE_INPUTS, NOTE_BUSES, NOTE_USER, NOTE_GROUP, NOTE_GLOBAL_VIEW, NOTE_SMPTE,
                                 NOTE_LED_SMPTE):
                        self.midi.short(h, 0x90, note, 0)
                    for k in range(8):
                        self.midi.short(h, 0x90, NOTE_F1 + k, 0)
                    for cc in list(range(CC_TIMECODE, CC_TIMECODE + 10)) + [CC_ASSIGN_L, CC_ASSIGN_R]:
                        self.midi.short(h, 0xB0, cc, 0x20)
                if u == self.master_unit:
                    self.midi.short(h, 0xE8, 0, 0)
                self.midi.long(h, X.msg_colors(dev, [7] * 8))
                self.midi.long(h, X.msg_lcd(dev, 0, " " * 112))
            except OSError:
                pass
