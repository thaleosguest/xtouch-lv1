#!/usr/bin/env python3
"""Scènes LV1 <-> marqueurs Reaper : côté pont (le côté Reaper est reaper/lv1_scenes.lua).

Échange par deux fichiers d'une ligne « n°\\tindex\\tnom » dans le dossier du script Lua :
    lv1_to_reaper.txt  : écrit ici à chaque scène rappelée sur la LV1 ;
    reaper_to_lv1.txt  : écrit par Reaper quand la lecture franchit un marqueur de scène -> on rappelle la scène.
LV1 (module Companion + journaux de Joseph) : /Notify/SceneList i:N (i index, s nom)×N, /Notify/CurSceneIndex i,
/Notify/Scene/Name s (scène courante) ; rappel : /Set/CurSceneIndex i (non vérifié sur la LV1 de Joseph).
"""
import os
import queue
import sys
import threading
import time

FOLDER = os.path.join((os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))), "reaper")
TO_REAPER, TO_LV1 = "lv1_to_reaper.txt", "reaper_to_lv1.txt"
TRACKS_FILE = "lv1_tracks.txt"            # entrées LV1 pour la synchro des pistes (reaper/lv1_sync_tracks.lua)


class SceneBridge:
    def __init__(self, folder=None, journal=None, poll=0.1):
        self.folder = folder or FOLDER
        self.mark = journal or (lambda _s: None)
        self.seq = int(time.time() * 1000)
        self.requests = queue.Queue()        # noms de scènes à rappeler sur la LV1
        self.poll = poll
        self.stop_flag = False
        self._tracks_last = None
        threading.Thread(target=self._watch, daemon=True).start()

    def scene_recalled(self, idx, name):
        """Scène rappelée sur la LV1 -> fichier lu par le script Reaper."""
        self.seq += 1
        path = os.path.join(self.folder, TO_REAPER)
        tmp = path + ".tmp"
        line = "%d\t%d\t%s\n" % (self.seq, idx, (name or "").replace("\t", " ").replace("\n", " "))
        for _ in range(20):                  # le script peut être en train de lire : on réessaie un instant
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(line)
                os.replace(tmp, path)
                self.mark("-> Reaper scène %d « %s »" % (idx, name))
                return True
            except OSError:
                time.sleep(0.01)
        self.mark("-> Reaper scène %d : fichier %s inaccessible" % (idx, path))
        return False

    def write_tracks(self, entries):
        """Entrées LV1 [(canal 0-based, nom, (r, g, b) ou None, stéréo)] -> lv1_tracks.txt (synchro des pistes),
        réécrit seulement s'il change. Une ligne par entrée : canal TAB nom TAB r TAB g TAB b TAB stéréo TAB rec TAB
        play (r = -1 : pas de couleur ; rec / play = canaux du pilote, 0-based, séparés par des virgules)."""
        lines = []
        for ent in entries:
            ch, name, rgb, stereo = ent[:4]
            rec, play = (ent[4], ent[5]) if len(ent) > 5 else ([], [])
            r, g, b = rgb if rgb else (-1, -1, -1)
            name = name.replace("\t", " ").replace("\n", " ")
            lines.append("%d\t%s\t%d\t%d\t%d\t%d\t%s\t%s\n" % (ch, name, r, g, b, 1 if stereo else 0,
                                                       ",".join(map(str, rec)), ",".join(map(str, play))))
        text = "".join(lines)
        if not entries or text == self._tracks_last:
            return False
        path = os.path.join(self.folder, TRACKS_FILE)
        try:
            with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(path + ".tmp", path)
        except OSError:
            return False
        self._tracks_last = text
        self.mark("-> Reaper liste des entrées LV1 (%d)" % len(entries))
        return True

    def _read(self):
        try:
            with open(os.path.join(self.folder, TO_LV1), encoding="utf-8") as f:
                line = f.readline()
        except (OSError, UnicodeDecodeError):
            return None
        if not line.endswith("\n"):          # en cours d'écriture
            return None
        parts = line.rstrip("\n").split("\t", 2)
        return (parts[0], parts[2]) if len(parts) == 3 else None

    def _watch(self):
        last = self._read()                  # demande déjà présente au démarrage : ancienne, ignorée
        last = last[0] if last else None
        while not self.stop_flag:
            time.sleep(self.poll)
            got = self._read()
            if got and got[0] != last:
                last = got[0]
                self.requests.put(got[1])
                self.mark("<- Reaper : marqueur de scène franchi « %s »" % got[1])


def scene_index(scenes, name):
    """Index LV1 de la scène de ce nom (le premier si plusieurs), ou None."""
    for idx, n in sorted(scenes.items()):
        if n == name:
            return idx
    return None
