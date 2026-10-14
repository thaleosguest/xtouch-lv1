#!/usr/bin/env python3
"""Lien avec X/M32 Gain Recall (x32-gain-recall, même auteur) : gain et 48 V des préamplis X32 par son API locale.

Le pont ne parle PAS à la X32 lui-même (choix de Joseph, 14/10/2026) : x32-gain-recall est déjà connecté,
connaît la correspondance canal LV1 -> EXP -> préampli (base de la LV1 + routing X32), et vérifie ses envois.

API utilisée (http://127.0.0.1:8032, pas de code d'accès depuis le PC lui-même) :
- GET  /api/state   : gains[idx] (dB), phantom[idx] (0|1), exp_map {idx: EXP}, lv1_sources {canal LV1: [EXP...]}
- POST /api/gain    {"idx": i, "db": x}  -> {"ok", "db" (valeur arrondie au pas de 0,5 dB)}
- POST /api/phantom {"idx": i, "on": bool}
idx = préampli global (console k : k*128 + i). Canal LV1 = numéro 1-based des entrées (groupe 0).

    py xgr_link.py            # affiche l'état lu (test, n'envoie rien)

Bibliothèque standard uniquement.
"""
import json
import queue
import sys
import threading
import time
import urllib.request

GAIN_MIN, GAIN_MAX, GAIN_STEP = -12.0, 60.0, 0.5
DEFAULT_URL = "http://127.0.0.1:8032"


def clamp_gain(db):
    db = max(GAIN_MIN, min(GAIN_MAX, db))
    return round(db / GAIN_STEP) * GAIN_STEP


class GainRecallLink(threading.Thread):
    """Lit l'état de x32-gain-recall (2 fois / s) et lui envoie gains et 48 V (file à part, regroupée)."""
    POLL = 0.5
    HOLD = 1.0          # s après un envoi pendant lesquelles l'état lu ne remplace pas la valeur locale

    def __init__(self, url=DEFAULT_URL, opener=None):
        super().__init__(daemon=True)
        self.url = url.rstrip("/")
        self.opener = opener or self._http
        self.lock = threading.Lock()
        self.ok = False             # dernier état lu avec succès et console connectée
        self.error = "pas encore lu"
        self.gains, self.phantom = {}, {}
        self.idx_of_exp = {}        # EXP -> préampli
        self.sources = {}           # canal LV1 (1-based) -> [EXP]
        self.touched = {}           # préampli -> instant du dernier envoi
        self.out = queue.Queue()
        self.stop_flag = False
        threading.Thread(target=self._sender, daemon=True).start()

    # ── HTTP ──
    def _http(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))

    # ── lecture ──
    def apply_state(self, st, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.ok = bool(st.get("connected"))
            self.error = "" if self.ok else "x32-gain-recall n'est pas connecté à la console"
            for i, g in enumerate(st.get("gains") or []):
                if g is not None and now - self.touched.get(i, 0) > self.HOLD:
                    self.gains[i] = float(g)
            for i, p in enumerate(st.get("phantom") or []):
                if now - self.touched.get(("ph", i), 0) > self.HOLD:
                    self.phantom[i] = bool(p)
            self.idx_of_exp = {int(e): int(i) for i, e in (st.get("exp_map") or {}).items() if e is not None}
            self.sources = {int(c): [int(e) for e in es] for c, es in (st.get("lv1_sources") or {}).items()}

    def run(self):
        while not self.stop_flag:
            try:
                self.apply_state(self.opener("GET", "/api/state"))
            except Exception as e:          # appli fermée, port pris… : on réessaie
                with self.lock:
                    self.ok, self.error = False, "x32-gain-recall injoignable (%s)" % e.__class__.__name__
            time.sleep(self.POLL)

    # ── correspondance ──
    def preamps(self, track):
        """Préamplis X32 d'une piste LV1 (groupe, canal 0-based) : [] si aucun (pas une entrée, pas d'EXP X32)."""
        g, ch = track
        if g != 0:
            return []
        with self.lock:
            return [self.idx_of_exp[e] for e in self.sources.get(ch + 1, []) if e in self.idx_of_exp]

    def gain(self, track, side=None):
        """Gain (dB) du préampli de la piste : side None = 1er, 0 = gauche, 1 = droite ; None si aucun."""
        p = self.preamps(track)
        k = side or 0
        with self.lock:
            return self.gains.get(p[k]) if k < len(p) else None

    def gains_of(self, track):
        """Gains de tous les préamplis de la piste (stéréo : [gauche, droite])."""
        p = self.preamps(track)
        with self.lock:
            return [self.gains.get(i) for i in p]

    def phantom_on(self, track, side=None):
        """48 V du préampli de la piste (side 0/1 = gauche/droite d'un stéréo ; None = le 1er)."""
        p = self.preamps(track)[(side or 0):(side or 0) + 1]
        with self.lock:
            return bool(p) and bool(self.phantom.get(p[0]))

    # ── écriture ──
    def nudge(self, track, delta_db, side=None):
        """Ajoute delta_db au préampli de la piste. Stéréo : side 0 = gauche, 1 = droite ; JAMAIS les deux à la
        fois (règle de Joseph, 14/10/2026) : side None = gauche. Renvoie le nouveau gain, ou None."""
        k = side or 0
        p = self.preamps(track)[k:k + 1]
        if not p:
            return None
        now = time.time()
        with self.lock:
            first = None
            for i in p:
                cur = self.gains.get(i)
                if cur is None:
                    continue
                new = clamp_gain(cur + delta_db)
                self.gains[i] = new
                self.touched[i] = now
                if first is None:
                    first = new
        for i in p:
            self.out.put(("gain", i))
        return first

    def set_phantom(self, track, on, side=None):
        """48 V d'UN préampli (stéréo : side 0/1, jamais les deux à la fois ; None = gauche)."""
        k = side or 0
        p = self.preamps(track)[k:k + 1]
        now = time.time()
        with self.lock:
            for i in p:
                self.phantom[i] = bool(on)
                self.touched[("ph", i)] = now
        for i in p:
            self.out.put(("phantom", i))
        return bool(p)

    def _sender(self):
        while True:
            kind, i = self.out.get()
            pending = {(kind, i)}
            time.sleep(0.03)                    # regroupe les crans rapides d'un encodeur
            try:
                while True:
                    pending.add(self.out.get_nowait())
            except queue.Empty:
                pass
            for kind, i in sorted(pending, key=str):
                try:
                    with self.lock:
                        if kind == "gain":
                            body, path = {"idx": i, "db": self.gains[i]}, "/api/gain"
                        else:
                            body, path = {"idx": i, "on": self.phantom[i]}, "/api/phantom"
                        self.touched[i if kind == "gain" else ("ph", i)] = time.time()
                    r = self.opener("POST", path, body)
                    if kind == "gain" and r.get("ok") and r.get("db") is not None:
                        with self.lock:
                            self.gains[i] = float(r["db"])
                except Exception as e:
                    with self.lock:
                        self.error = "envoi %s refusé (%s)" % (kind, e.__class__.__name__)


def main():
    link = GainRecallLink(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
    link.start()
    time.sleep(1.5)
    print("Connecté :", link.ok, link.error)
    for c in range(1, 17):
        tr = (0, c - 1)
        print("  In %2d : préamplis %-10s gain %-6s 48V %s" % (c, link.preamps(tr), link.gain(tr), link.phantom_on(tr)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
