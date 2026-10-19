"""Faders motorisés X-Touch <-> faders des pistes LV1 : toucher, geste, retours LV1 tenus / périmés, ongle (fader bougé
sans toucher), moteur.

Déplacé de `xtouch_lv1_display.py` (étape 8e du refactor, 19/10/2026)."""
from bridge.journal import JOURNAL
from bridge.values import fader_to_db
from surface.notes import MASTER, TOUCH_NOTES


HOLD_AFTER = 0.3        # s pendant lesquelles un fader lâché reste « tenu » (retours LV1 ignorés)
MOTOR_BUSY = 1.5        # s après une commande moteur : un fader bougé sans toucher est le moteur, pas la main
NAIL_SHOW = 0.15        # s : point de toucher d'un fader bougé sans toucher détecté, après son dernier mouvement
UNTOUCHED_MIN = 80      # écart (sur 16383) qu'un fader non touché doit faire pour démarrer un geste (ongle)
STALE_FOR = 2.0         # s après le relâchement pendant lesquelles un retour « périmé » est ignoré
SEND_EVERY = 0.02       # envoi max d'une valeur par fader toutes les 20 ms


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
