"""Journal du pont : messages LV1 (arguments complets) et marques horodatées « ===== … ».

Déplacé de `xtouch_lv1_display.py` (étape 8a du refactor, 19/10/2026)."""
import lv1_probe as L
import threading
import time


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


class JournalSlot:
    """Le journal en cours, partagé par tous les modules du pont. Avant l'étape 8a, main() remplaçait la variable
    globale (`JOURNAL = Journal(chemin)`) : un module à part aurait gardé l'ancien. On change donc ce que l'emplacement
    contient (`JOURNAL.current = Journal(chemin)`), et chacun écrit au même endroit."""

    def __init__(self, journal):
        self.current = journal

    def write(self, address, args):
        self.current.write(address, args)

    def mark(self, text):
        self.current.mark(text)


JOURNAL = JournalSlot(Journal(None))
