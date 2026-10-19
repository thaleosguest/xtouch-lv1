"""Côté REAPER de la X-Touch : transport (lecture, arrêt, enregistrement, boucle, marqueurs, jog) et bascule
LV1 <-> REAPER + SAVE (AppControl).

Déplacé de `xtouch_lv1_display.py` (étape 8h du refactor, 19/10/2026)."""
import threading
import time

from bridge.journal import JOURNAL
from surface.notes import (NOTE_CLICK, NOTE_CYCLE, NOTE_DISPLAY, NOTE_DOWN, NOTE_DROP, NOTE_ENTER, NOTE_FF,
                           NOTE_LEFT, NOTE_MARKER, NOTE_PLAY, NOTE_RECORD, NOTE_REPLACE, NOTE_REW, NOTE_RIGHT,
                           NOTE_SAVE, NOTE_SCRUB, NOTE_STOP, NOTE_UP, NOTE_ZOOM, TRANSPORT_NOTES)


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
