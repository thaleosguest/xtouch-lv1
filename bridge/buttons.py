"""Boutons des tranches et de la X-Touch : Mute / Solo / Select, BANK / CHANNEL, touches View (INPUTS, BUSES, USER,
GROUP, GLOBAL VIEW) et leurs voyants, SMPTE, User Keys F1-F8.

Déplacé de `xtouch_lv1_display.py` (étape 8g du refactor, 19/10/2026)."""
from bridge.journal import JOURNAL
from bridge.lv1_watch import FollowsView
from surface.notes import (CC_JOG, MASTER, NOTE_BANK_LEFT, NOTE_BANK_RIGHT, NOTE_BUSES, NOTE_CHANNEL_LEFT,
                           NOTE_CHANNEL_RIGHT, NOTE_FLIP, NOTE_GLOBAL_VIEW, NOTE_GROUP, NOTE_INPUTS, NOTE_MUTE,
                           NOTE_REC, NOTE_SELECT, NOTE_SMPTE, NOTE_SOLO, NOTE_SOLO_ALL, NOTE_USER)


def view_leds(mode, tab=None, spill=False):
    """Voyants des touches View : mode de couche (lv1_db.MODE_*), onglet affiché, Spill lu à l'écran ; {note: allumée}.
    Inconnu : éteint. Spill allumé : la base garde le mode d'avant (4), mais seul Spill est allumé sur la LV1 -> seul
    GROUP. GLOBAL VIEW = onglet All (Joseph, 16/10)."""
    spill = bool(spill or mode == 3)
    return {NOTE_INPUTS: mode in (0, 4) and not spill, NOTE_BUSES: mode == 5 and not spill,
            NOTE_USER: mode == 1 and not spill, NOTE_GROUP: spill, NOTE_GLOBAL_VIEW: tab == "All"}


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
