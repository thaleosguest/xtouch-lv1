"""Touche TRACK : encodeurs sur le gain des préamplis X32 (via X/M32 Gain Recall), Rec tenu = 48 V ; PAN.

Déplacé de `xtouch_lv1_display.py` (étape 8c du refactor, 19/10/2026)."""
import time

from bridge.journal import JOURNAL
from bridge.values import LV1_PAN_SCALE, pan_label
from surface.display import SIDE_NAMES, gain_label
from surface.notes import CC_VPOT, NOTE_PAN, NOTE_REC, NOTE_TRACK, NOTE_VPOT_PUSH


class GainControl:
    """Étape 4 : TRACK = encodeurs sur le gain des préamplis X32 ; Rec tenu 1 s = 48 V. Via x32-gain-recall.

    Choix de Joseph (14/10/2026) : le gain X32 passe par x32-gain-recall (xgr_link), pas directement à la X32.
    48 V : il faut TENIR Rec PHANTOM_HOLD s (relâchement après) pour basculer, un appui bref ne fait rien
    (protection des micros à ruban). LED Rec = état 48 V réel, toujours (pas seulement en mode gain)."""
    STEP_DB = 0.5
    PHANTOM_HOLD = 1.0

    PAN_STEP = 3.0 / 45.0             # 1 cran = 3 pas de l'échelle LV1 (L45..R45) ; « pas assez sensible » à 1
    PAN_FAST = 0.08                   # s : crans plus rapprochés -> pas doublé
    PAN_HOLD = 0.5                    # s : retours LV1 de pan ignorés après notre envoi

    def __init__(self, state, link, write=True, lv1=None):
        self.state, self.link, self.write = state, link, write
        self.lv1 = lv1                    # LV1Link (envoi /Set/Track/Pan)
        self.mode = False                 # mode gain (TRACK)
        self.pan_mode = False             # mode pan (PAN) ; exclusif avec le mode gain
        self.pan_last = {}                # tranche -> instant du dernier cran (accélération)
        self.rec_down = {}                # tranche -> instant d'appui sur Rec
        self.side = {}                    # piste stéréo -> 0 (L, défaut) / 1 (R) : appui encodeur ; jamais les deux
        self.warned = set()
        self.send_aux = lambda: None      # aux en sends on fader (branché sur SendControl) : PAN = pan de l'envoi

    def on_midi(self, unit, status, d1, d2, t, entries, surface):
        kind = status & 0xF0
        if kind == 0x90 and d1 == NOTE_TRACK:
            if d2:
                self.mode = not self.mode
                self.pan_mode = False
                if not self.mode:
                    self.side.clear()             # en sortant du mode gain : stéréo de nouveau sur L
                JOURNAL.mark("XT bouton Track -> mode gain %s" % ("ON" if self.mode else "OFF"))
            return True
        if kind == 0x90 and d1 == NOTE_PAN:
            if d2:
                self.pan_mode = not self.pan_mode
                if self.pan_mode:
                    self.mode = False
                    self.side.clear()
                JOURNAL.mark("XT bouton Pan -> mode pan %s" % ("ON" if self.pan_mode else "OFF"))
            return True
        if self.pan_mode and kind == 0x90 and NOTE_VPOT_PUSH <= d1 < NOTE_VPOT_PUSH + 8:
            strip = 8 * unit + (d1 - NOTE_VPOT_PUSH)
            e = entries[strip] if strip < len(entries) else None
            if d2 and e is not None:
                self._set_pan(e, 0.0, "appui encodeur %d -> pan centre" % (strip + 1))
            return True
        if self.pan_mode and kind == 0xB0 and CC_VPOT <= d1 < CC_VPOT + 8:
            strip = 8 * unit + (d1 - CC_VPOT)
            n = d2 & 0x0F
            delta = -n if d2 & 0x40 else n
            e = entries[strip] if strip < len(entries) else None
            if e is None or not delta:
                return True
            with self.state.lock:
                cur = self.state.tracks.get(e, {}).get("pan")
            if cur is None:
                self._warn("pan de départ inconnu pour %s : encodeur sans effet (bouge-le une fois sur la LV1)" % (e,))
                return True
            fast = t - self.pan_last.get(strip, 0) < self.PAN_FAST
            self.pan_last[strip] = t
            step = self.PAN_STEP * (2 if fast else 1)
            self._set_pan(e, max(-1.0, min(1.0, round((cur + delta * step) * 45) / 45.0)),
                          "encodeur %d %+d%s" % (strip + 1, delta, " rapide" if fast else ""))
            return True
        if kind == 0x90 and NOTE_VPOT_PUSH <= d1 < NOTE_VPOT_PUSH + 8:
            strip = 8 * unit + (d1 - NOTE_VPOT_PUSH)
            e = entries[strip] if strip < len(entries) else None
            if d2 and self.mode and e is not None and self.link and len(self.link.preamps(e)) == 2:
                nxt = 1 - self.side.get(e, 0)
                self.side[e] = nxt
                JOURNAL.mark("XT appui encodeur %d -> stéréo %s %s" % (strip + 1, SIDE_NAMES[nxt], e))
            return True
        if kind == 0xB0 and CC_VPOT <= d1 < CC_VPOT + 8:
            strip = 8 * unit + (d1 - CC_VPOT)
            n = d2 & 0x0F
            delta = -n if d2 & 0x40 else n
            e = entries[strip] if strip < len(entries) else None
            if not self.mode or e is None or not delta:
                return True
            if not self.link:
                self._warn("pas de lien x32-gain-recall")
                return True
            if self.write:
                new = self.link.nudge(e, delta * self.STEP_DB, self.side.get(e))
                JOURNAL.mark("XT encodeur %d %+d -> gain %s %s" % (strip + 1, delta, e, new))
                if new is None:
                    self._warn("piste %s : pas de préampli X32 (ou gains pas encore lus)" % (e,))
            return True
        if kind == 0x90 and NOTE_REC <= d1 < NOTE_REC + 8:
            strip = 8 * unit + (d1 - NOTE_REC)
            if d2:
                self.rec_down[strip] = t
                return True
            t0 = self.rec_down.pop(strip, None)
            e = entries[strip] if strip < len(entries) else None
            if t0 is None or e is None or not self.link:
                return True
            if t - t0 < self.PHANTOM_HOLD:
                JOURNAL.mark("XT Rec tranche %d : appui bref (%.1f s), 48 V inchangé" % (strip + 1, t - t0))
                self._warn("48 V : tenir Rec %.0f s" % self.PHANTOM_HOLD)
                return True
            side = self.side.get(e, 0)
            on = not self.link.phantom_on(e, side)
            if self.write and self.link.set_phantom(e, on, side):
                JOURNAL.mark("XT Rec tranche %d tenu -> 48 V %s %s côté %s" % (strip + 1, "ON" if on else "OFF", e,
                                                                         SIDE_NAMES[side]))
            return True
        return False

    def _set_pan(self, e, value, why):
        with self.state.lock:
            self.state.track(*e)["pan"] = value
            self.state.pan_hold[e] = time.time() + self.PAN_HOLD
        if self.write and self.lv1:
            self.lv1.send("/Set/Track/Pan", [("i", e[0]), ("i", e[1]), ("d", value * LV1_PAN_SCALE)])
        JOURNAL.mark("XT %s -> pan %s %+.3f" % (why, e, value))

    def _warn(self, text):
        if text not in self.warned:
            print("  %s" % text)
            self.warned.add(text)

    def frame(self, entries, bot):
        """Ligne du bas (gain en mode gain), couronnes, LED Rec (48 V) pour les tranches affichées."""
        rings, recs = [], []
        if self.pan_mode:
            aux = self.send_aux()        # sends on fader : on montre le pan de l'ENVOI (c'est lui que règlent les encodeurs)
            with self.state.lock:
                if aux is not None:
                    pans = [self.state.sends.get((e[0], e[1], aux), {}).get("pan") if e is not None else None
                            for e in entries]
                else:
                    pans = [self.state.tracks.get(e, {}).get("pan") if e is not None else None for e in entries]
        for i, e in enumerate(entries):
            if self.pan_mode:
                p = pans[i]
                recs.append(bool(self.link and e is not None and self.link.phantom_on(e, self.side.get(e, 0))))
                rings.append(0 if p is None else (6 + int(round(p * 5))))     # mode 0 : un point, centre = 6
                if e is not None and i < len(bot):
                    bot[i] = pan_label(p)
                continue
            side = self.side.get(e, 0)
            g = self.link.gain(e, side) if (self.link and e is not None) else None
            recs.append(bool(self.link and e is not None and self.link.phantom_on(e, side)))
            if self.mode and g is not None:   # (gain_label : côté réglé du stéréo)
                pos = 1 + int(round((g + 12.0) / 72.0 * 10))
                rings.append(0x20 | max(1, min(11, pos)))       # mode 2 : remplissage depuis la gauche
                if i < len(bot):
                    bot[i] = gain_label(self.link.gains_of(e), side)
            else:
                rings.append(0)
                if self.mode and i < len(bot) and e is not None:
                    bot[i] = "  -"
        return rings, recs
