-- LV1 : synchroniser les pistes (xtouch-lv1-bridge, demande de Joseph du 15/10/2026), comme la synchro de Tracks Live.
-- Crée / met à jour une piste Reaper par entrée de la LV1, dans l'ordre de la LV1 : nom et couleur du canal.
-- Liste écrite par le pont (xtouch_lv1_display.py) dans lv1_tracks.txt, à côté de ce script :
--   canal (0-based) TAB nom TAB r TAB g TAB b TAB stéréo(0|1)   (r = -1 : pas de couleur)
-- Les pistes créées ici sont marquées (P_EXT:lv1_in = n° de canal) : on les retrouve aux synchros suivantes et on ne
-- touche jamais aux autres pistes. Rien n'est supprimé. Mono / stéréo est noté (P_EXT:lv1_stereo) pour le routage.
-- Installation : Actions > Show action list > New action > Load ReaScript… > ce fichier ; lancer à chaque synchro.

local dir = ({reaper.get_action_context()})[2]:match("^(.*[\\/])")
local FILE = dir .. "lv1_tracks.txt"

local function read_list()
  local f = io.open(FILE, "r")
  if not f then return nil end
  local list = {}
  for line in f:lines() do
    local ch, name, r, g, b, st = line:match("^(%d+)\t(.-)\t(%-?%d+)\t(%-?%d+)\t(%-?%d+)\t(%d)$")
    if ch then
      r, g, b = tonumber(r), tonumber(g), tonumber(b)
      list[#list + 1] = {ch = tonumber(ch), name = name, stereo = st == "1",
                         color = r >= 0 and (reaper.ColorToNative(r, g, b) | 0x1000000) or 0}
    end
  end
  f:close()
  return list
end

local function tagged_tracks()
  local map = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local ok, v = reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_in", "", false)
    if ok and v ~= "" then map[tonumber(v)] = tr end
  end
  return map
end

local function is_default_name(e)
  return e.name == "" or e.name == ("Channel " .. (e.ch + 1))
end

local list = read_list()
if not list or #list == 0 then
  reaper.ShowMessageBox("Aucune liste d'entrées LV1 (" .. FILE .. ").\nLe pont xtouch_lv1_display.py tourne-t-il, connecté à la LV1 ?",
                        "LV1 : synchroniser les pistes", 0)
  return
end
local tagged = tagged_tracks()
local named, existing = 0, 0
for _, e in ipairs(list) do
  if not is_default_name(e) then named = named + 1 end
  if tagged[e.ch] then existing = existing + 1 end
end
local answer = reaper.ShowMessageBox(string.format(
  "%d entrées LV1 (%d renommées), %d déjà présentes dans Reaper.\n\n" ..
  "OUI : toutes les entrées\nNON : seulement les entrées renommées (pas « Channel N »)\nANNULER : ne rien faire\n\n" ..
  "Les pistes existantes prennent le nom et la couleur de la LV1. Rien n'est supprimé.",
  #list, named, existing), "LV1 : synchroniser les pistes", 3)
if answer ~= 6 and answer ~= 7 then return end
local only_named = answer == 7

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)
local created, updated, last = 0, 0, -1
for _, e in ipairs(list) do
  local tr = tagged[e.ch]
  if tr or not only_named or not is_default_name(e) then
    if not tr then
      reaper.InsertTrackAtIndex(last + 1, true)
      tr = reaper.GetTrack(0, last + 1)
      reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_in", tostring(e.ch), true)
      created = created + 1
    else
      updated = updated + 1
    end
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", e.name, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", e.color)
    reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_stereo", e.stereo and "1" or "0", true)
    last = math.floor(reaper.GetMediaTrackInfo_Value(tr, "IP_TRACKNUMBER")) - 1
  end
end
reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.Undo_EndBlock("LV1 : synchroniser les pistes", -1)
reaper.ShowMessageBox(string.format("%d pistes créées, %d mises à jour.", created, updated),
                      "LV1 : synchroniser les pistes", 0)
