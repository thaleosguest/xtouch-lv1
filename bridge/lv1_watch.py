"""Ce que le pont fait sur l'écran de la LV1 : clics simulés (LV1Clicker), mode de couche lu dans la base
(LayerModeWatcher), Mixer / onglet suivi (ViewFollower), tranche sélectionnée (LV1SelectionWatcher) ; FollowsView.

Déplacé de `xtouch_lv1_display.py` (étape 8f du refactor, 19/10/2026)."""
import queue
import sys
import threading
import time

from bridge.journal import JOURNAL


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
    d'onglets (positions décalées) -> son onglet peut être mal lu (cas 2 écrans, hors de l'usage de Joseph).
    busy() vrai (fader sous le doigt, ou relâché depuis moins de HOLD_AFTER) : changement de Mixer DIFFÉRÉ (étape 10,
    19/10) — sinon le fader tenu écrivait sur la tranche du même numéro dans l'autre Mixer. Il se fait au lâcher, si la
    LV1 montre toujours l'autre Mixer."""
    PERIOD = 0.2

    def __init__(self, state, fixed=None, read=None, busy=lambda: False):
        super().__init__(daemon=True)
        self.state, self.fixed, self.busy = state, fixed, busy
        self.deferred = None             # Mixer en attente pendant un toucher (pour ne le noter qu'une fois)
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
                elif self.busy():
                    if new != self.deferred:
                        self.deferred = new
                        JOURNAL.mark("Mixer %d affiché : changement différé (fader touché)" % (new + 1))
                    new = None
                else:
                    self.state.view = new
            if new is not None or self.fixed is not None or not self.busy():
                self.deferred = None
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
