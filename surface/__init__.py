"""Côté surface X-Touch : ce qui ne dépend QUE du matériel Behringer (notes MIDI, couleurs, rendu).

Rien ici ne connaît la LV1, REAPER ou la X32. Étape 1 du refactor (19/10/2026) : seules les constantes sont
arrivées (`notes.py`) ; le MIDI et le rendu suivront (étape 6). `xtouch_lv1_display` les réexporte, donc les
anciens noms (`D.NOTE_TRACK`…) continuent de marcher.
"""
