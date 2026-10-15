-- LV1 : synchroniser les pistes (xtouch-lv1-bridge, demande de Joseph du 15/10/2026), comme la synchro de Tracks Live.
-- Crée / met à jour une piste Reaper par entrée de la LV1, dans l'ordre de la LV1 : nom, couleur, et ROUTAGE vers le
-- pilote SoundGrid de ce PC (lu dans la base LV1 par le pont) : entrée d'enregistrement = canaux du pilote qui
-- reçoivent la source de l'entrée A ; sortie matérielle = canaux de lecture branchés sur l'entrée B (virtual
-- soundcheck). Les pistes créées ici sont marquées (P_EXT:lv1_in) : on ne touche jamais aux autres. Rien n'est
-- supprimé. Liste : lv1_tracks.txt (voir lv1_common.lua).
-- Installation : Actions > Show action list > New action > Load ReaScript… > ce fichier ; lancer à chaque synchro.

local dir = ({reaper.get_action_context()})[2]:match("^(.*[\\/])")
local C = dofile(dir .. "lv1_common.lua")
local TITLE = "LV1 : synchroniser les pistes"

local text = C.read(dir .. "lv1_tracks.txt")
local list = text and C.parse(text) or {}
if #list == 0 then
  reaper.ShowMessageBox("Aucune liste d'entrées LV1 (" .. dir .. "lv1_tracks.txt).\n" ..
                        "Le pont xtouch_lv1_display.py tourne-t-il, connecté à la LV1 ?", TITLE, 0)
  return
end
if reaper.GetPlayState() & 4 == 4 then
  reaper.ShowMessageBox("Enregistrement en cours : synchro impossible (elle change les entrées des pistes).", TITLE, 0)
  return
end
local tagged = C.tagged_tracks()
local named, existing, routed = 0, 0, 0
for _, e in ipairs(list) do
  if not C.is_default_name(e) then named = named + 1 end
  if tagged[e.ch] then existing = existing + 1 end
  if #e.rec > 0 or #e.play > 0 then routed = routed + 1 end
end
local answer = reaper.ShowMessageBox(string.format(
  "%d entrées LV1 (%d renommées, %d routées vers le pilote de ce PC), %d déjà présentes dans Reaper.\n\n" ..
  "OUI : toutes les entrées\nNON : seulement les entrées renommées (pas « Channel N »)\nANNULER : ne rien faire\n\n" ..
  "Les pistes prennent le nom, la couleur et le routage de la LV1 (entrée d'enregistrement, sortie vers l'entrée B).\n" ..
  "Rien n'est supprimé, les autres pistes ne sont pas touchées.",
  #list, named, routed, existing), TITLE, 3)
if answer ~= 6 and answer ~= 7 then return end
local only_named = answer == 7
-- choix gardé dans le projet : lv1_scenes.lua ajoute ensuite tout seul les nouvelles entrées (Reaper à l'arrêt)
reaper.SetProjExtState(0, "lv1", "sync_mode", only_named and "named" or "all")

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)
local created, updated, last = 0, 0, -1
for _, e in ipairs(list) do
  local tr = tagged[e.ch]
  if tr or not only_named or not C.is_default_name(e) then
    if not tr then
      tr = C.new_track(last + 1, e)
      created = created + 1
    else
      updated = updated + 1
    end
    C.apply_look(tr, e)
    C.apply_routing(tr, e)
    last = math.floor(reaper.GetMediaTrackInfo_Value(tr, "IP_TRACKNUMBER")) - 1
  end
end
reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.Undo_EndBlock("LV1 : synchroniser les pistes", -1)
reaper.ShowMessageBox(string.format("%d pistes créées, %d mises à jour.", created, updated), TITLE, 0)
