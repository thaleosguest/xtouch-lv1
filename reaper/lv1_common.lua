-- Fonctions communes aux scripts LV1 de Reaper (lv1_scenes.lua, lv1_sync_tracks.lua) — xtouch-lv1-bridge.
-- Chargé par dofile(). Liste écrite par le pont dans lv1_tracks.txt, une ligne par entrée LV1 :
--   canal (0-based) TAB nom TAB r TAB g TAB b TAB stéréo(0|1) TAB rec TAB play
--   rec / play : canaux du pilote SoundGrid de ce PC (0-based, « 0,1 » = paire) ; rec = à enregistrer (source de
--   l'entrée A envoyée au pilote), play = lecture branchée sur l'entrée B de la LV1 (virtual soundcheck).
local M = {}

local function list_of(s)
  local t = {}
  for n in (s or ""):gmatch("%d+") do t[#t + 1] = tonumber(n) end
  return t
end

function M.parse(text)
  local entries = {}
  for line in text:gmatch("[^\n]+") do
    local ch, name, r, g, b, st, rest = line:match("^(%d+)\t(.-)\t(%-?%d+)\t(%-?%d+)\t(%-?%d+)\t(%d)(.*)$")
    if ch then
      local rec, play = rest:match("^\t([%d,]*)\t([%d,]*)$")
      r, g, b = tonumber(r), tonumber(g), tonumber(b)
      entries[#entries + 1] = {ch = tonumber(ch), name = name, stereo = st == "1",
                               color = r >= 0 and (reaper.ColorToNative(r, g, b) | 0x1000000) or 0,
                               rec = list_of(rec), play = list_of(play)}
    end
  end
  return entries
end

function M.read(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local text = f:read("a")
  f:close()
  return text
end

function M.is_default_name(e)
  return e.name == "" or e.name == ("Channel " .. (e.ch + 1))
end

-- Entrée retenue selon le choix de synchro : "routed" = son entrée A est enregistrée par le pilote de ce PC ;
-- "named" (ancien choix) = renommée ; "all" = toutes.
function M.wanted(e, mode)
  if mode == "routed" then return #e.rec > 0 end
  if mode == "named" then return not M.is_default_name(e) end
  return mode == "all"
end

function M.tagged_tracks()
  local map = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local ok, v = reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_in", "", false)
    if ok and v ~= "" then map[tonumber(v)] = tr end
  end
  return map
end

-- Nom et couleur (toujours sans danger)
function M.apply_look(tr, e)
  local _, cur = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
  if cur ~= e.name then reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", e.name, true) end
  if math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR")) ~= e.color then
    reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", e.color)
  end
  reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_stereo", e.stereo and "1" or "0", true)
end

local function pair(t)                      -- {n, n+1} = paire stéréo
  return #t >= 2 and t[2] == t[1] + 1
end

-- Sortie vers la LV1 : canaux « play » (lecture branchée sur l'entrée B) ; si l'entrée B n'est pas sur le pilote, on
-- sort sur les MÊMES numéros que l'enregistrement (Joseph, 15/10 : canal 1 A = EXP 3 -> enregistré sur LV1-PORT 3 ;
-- il suffit de mettre l'entrée B = LV1-PORT 3 pour le Flip B, sans refaire la synchro).
function M.out_of(e)
  if #e.play > 0 then return e.play end
  return e.rec
end

-- Entrée B branchée sur un autre numéro que l'enregistrement ?
function M.mismatch(e)
  return #e.play > 0 and #e.rec > 0 and e.play[1] ~= e.rec[1]
end

-- Routage : entrée d'enregistrement = canaux « rec » du pilote ; sortie matérielle = M.out_of (entrée B).
-- La sortie matérielle créée ici est marquée (P_EXT:lv1) : on ne touche jamais aux autres envois de la piste.
-- À n'appeler que Reaper à l'ARRÊT (changer l'entrée d'une piste en enregistrement couperait la prise).
function M.apply_routing(tr, e)
  local want_in = -1
  if #e.rec > 0 then want_in = pair(e.rec) and (1024 + e.rec[1]) or e.rec[1] end
  if want_in >= 0 and math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT")) ~= want_in then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", want_in)
  end
  local ours = nil
  for i = 0, reaper.GetTrackNumSends(tr, 1) - 1 do       -- catégorie 1 = sorties matérielles
    local ok, v = reaper.GetSetTrackSendInfo_String(tr, 1, i, "P_EXT:lv1", "", false)
    if ok and v == "1" then ours = i end
  end
  local out = M.out_of(e)
  if #out == 0 then
    if ours then reaper.RemoveTrackSend(tr, 1, ours) end
    return
  end
  if not ours then
    ours = reaper.CreateTrackSend(tr, nil)
    reaper.GetSetTrackSendInfo_String(tr, 1, ours, "P_EXT:lv1", "1", true)
  end
  local dst = pair(out) and out[1] or (1024 + out[1])           -- &1024 = sortie mono
  local src = pair(out) and 0 or 1024                           -- piste mono : canal 1 seul
  if math.floor(reaper.GetTrackSendInfo_Value(tr, 1, ours, "I_DSTCHAN")) ~= dst then
    reaper.SetTrackSendInfo_Value(tr, 1, ours, "I_DSTCHAN", dst)
  end
  if math.floor(reaper.GetTrackSendInfo_Value(tr, 1, ours, "I_SRCCHAN")) ~= src then
    reaper.SetTrackSendInfo_Value(tr, 1, ours, "I_SRCCHAN", src)
  end
end

function M.new_track(index, e)
  reaper.InsertTrackAtIndex(index, true)
  local tr = reaper.GetTrack(0, index)
  reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_in", tostring(e.ch), true)
  return tr
end

return M
