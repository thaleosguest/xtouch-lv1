"""Côté surface X-Touch : ce qui ne dépend QUE du matériel Behringer (notes MIDI, couleurs, rendu).

Rien ici ne connaît la LV1, REAPER ou la X32. Refactor du 19/10/2026 : `notes.py` (étape 1 : notes, CC, couleurs),
`midi.py` (entrées / sorties winmm), `xtouch.py` (classe Surface : envoi de ce qui change), `display.py` (textes et
codes 7 segments) (étape 6). `xtouch_lv1_display` les réexporte, donc les anciens noms (`D.NOTE_TRACK`,
`D.Surface`, `D.seg_codes`…) continuent de marcher.
"""
