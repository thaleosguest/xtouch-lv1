#!/usr/bin/env python3
"""Lecture de la base de travail de la LV1 (CurrentLV1.dat) pour ce que le réseau ne donne pas à la connexion.

La LV1 écrit ses réglages en continu dans C:\\Users\\Public\\Waves Audio\\eMotion\\Sessions\\CurrentLV1.dat
(SQLite, mode WAL), cf. x32-gain-recall. On ne l'ouvre JAMAIS directement (SQLite y créerait -shm/-wal et des
verrous) : copie du fichier + -wal dans un dossier temporaire, lecture de la copie.

Pan (vérifié le 14/10/2026, LV1 V17) : snapshot_chainer_params, snapshot -1, param 436 PARAM_OUTPUT_BALANCE,
-45 (gauche) .. +45 (droite) ; absent = centre. Réseau (/Notify/Track/Pan, /Set/Track/Pan) : -1 .. +1.
chainer_id = object.id ; object.obj_type 0 = entrées, obj_index = canal 0-based.

    py lv1_db.py          # affiche les pans des entrées
"""
import os
import shutil
import sqlite3
import sys
import tempfile

DB_PATH = r"C:\Users\Public\Waves Audio\eMotion\Sessions\CurrentLV1.dat"
PARAM_BALANCE = 436
BALANCE_SCALE = 45.0


def copy_db(path=DB_PATH):
    """Copie (fichier + -wal) dans un dossier temporaire ; renvoie le chemin de la copie (à effacer)."""
    d = tempfile.mkdtemp(prefix="lv1db_")
    dst = os.path.join(d, "c.dat")
    shutil.copyfile(path, dst)
    if os.path.exists(path + "-wal"):
        shutil.copyfile(path + "-wal", dst + "-wal")
    return dst


def input_pans(path=DB_PATH):
    """{(0, canal 0-based): pan -1..+1} pour toutes les entrées connues de la base."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            objs = db.execute("select id, obj_index from object where obj_type = 0").fetchall()
            vals = dict(db.execute("select chainer_id, param_value from snapshot_chainer_params "
                                   "where snapshot_id = -1 and param_id = ?", (PARAM_BALANCE,)).fetchall())
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    return {(0, idx): max(-1.0, min(1.0, float(vals.get(oid, 0.0)) / BALANCE_SCALE)) for oid, idx in objs}


def main():
    pans = input_pans(sys.argv[1] if len(sys.argv) > 1 else DB_PATH)
    for (g, ch), p in sorted(pans.items())[:16]:
        print("  In %2d : pan %+.2f" % (ch + 1, p))
    print("(%d entrées)" % len(pans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
