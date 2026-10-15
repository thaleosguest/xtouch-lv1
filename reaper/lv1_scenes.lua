-- Scènes LV1 <-> marqueurs Reaper (xtouch-lv1-bridge, demande de Joseph du 15/10/2026), comme « Create/Recall
-- Scenes » de Tracks Live :
--   * ENREGISTREMENT : une scène rappelée sur la LV1 pose un marqueur VERT au nom de la scène, au curseur de lecture ;
--   * LECTURE : quand la lecture franchit un marqueur de scène, la scène est rappelée sur la LV1 (virtual soundcheck) ;
--     sauter dans la timeline ne rappelle rien (seuls les marqueurs réellement franchis comptent) ;
--   * ARRÊT : une scène rappelée sur la LV1 place le curseur sur le marqueur du même nom.
-- Le pont (xtouch_lv1_display.py) et ce script s'échangent les scènes par deux petits fichiers posés à côté de ce
-- script : lv1_to_reaper.txt (pont -> Reaper) et reaper_to_lv1.txt (Reaper -> pont), une ligne « n°\tindex\tnom ».
-- Marqueur de scène = marqueur de la couleur SCENE_COLOR (ne pas la changer à la main, sinon il n'est plus reconnu).
--
-- Installation : Actions > Show action list > New action > Load ReaScript… > ce fichier, puis Run. Pour le lancer
-- à chaque démarrage : extension SWS (Startup actions) ou __startup.lua. Relancer l'action l'arrête (bascule).

local dir = ({reaper.get_action_context()})[2]:match("^(.*[\\/])")
local IN_FILE, OUT_FILE = dir .. "lv1_to_reaper.txt", dir .. "reaper_to_lv1.txt"
local SCENE_COLOR = reaper.ColorToNative(40, 200, 90) | 0x1000000
local MAX_STEP = 0.5            -- s : avance de lecture au-delà de laquelle c'est un saut (rien n'est rappelé)

local last_seq = nil            -- dernier événement LV1 traité (nil = pas encore lu : on prend la référence)
local out_seq = math.floor(reaper.time_precise() * 1000)
local last_pos = nil            -- position de lecture au tour précédent (nil = arrêté)

local function read_in()
  local f = io.open(IN_FILE, "r")
  if not f then return nil end
  local line = f:read("l")
  f:close()
  if not line then return nil end
  local seq, idx, name = line:match("^(%d+)\t(%-?%d+)\t(.*)$")
  if not seq then return nil end
  return seq, tonumber(idx), name
end

local function write_out(name)
  out_seq = out_seq + 1
  local f = io.open(OUT_FILE, "w")
  if f then
    f:write(string.format("%d\t-1\t%s\n", out_seq, name))
    f:close()
  end
end

local function scene_markers()
  local list, i = {}, 0
  while true do
    local ok, isrgn, pos, _, name, _, color = reaper.EnumProjectMarkers3(0, i)
    if ok == 0 then break end
    if not isrgn and color == SCENE_COLOR then list[#list + 1] = {pos = pos, name = name} end
    i = i + 1
  end
  return list
end

local function on_lv1_scene(name)
  local st = reaper.GetPlayState()
  if st & 4 == 4 then                                     -- enregistrement : marqueur vert au nom de la scène
    reaper.Undo_BeginBlock()
    reaper.AddProjectMarker2(0, false, reaper.GetPlayPosition(), 0, name, -1, SCENE_COLOR)
    reaper.Undo_EndBlock("LV1 : marqueur de scène " .. name, -1)
  elseif st & 1 == 0 then                                 -- arrêt (ou pause) : curseur sur le marqueur de la scène
    for _, m in ipairs(scene_markers()) do
      if m.name == name then
        reaper.SetEditCurPos(m.pos, true, false)
        break
      end
    end
  end                                                     -- lecture : rien (c'est nous qui venons de la rappeler)
end

local function check_crossing()
  local st = reaper.GetPlayState()
  if st & 1 == 0 or st & 4 == 4 then                      -- arrêté, ou en enregistrement : on ne rappelle rien
    last_pos = nil
    return
  end
  local pos = reaper.GetPlayPosition()
  if last_pos and pos > last_pos and pos - last_pos < MAX_STEP then
    local crossed = nil
    for _, m in ipairs(scene_markers()) do
      if m.pos > last_pos and m.pos <= pos then crossed = m end
    end
    if crossed then write_out(crossed.name) end
  end
  last_pos = pos
end

local function loop()
  local seq, _, name = read_in()
  if seq and seq ~= last_seq then
    if last_seq ~= nil then on_lv1_scene(name) end         -- au premier tour : simple référence
    last_seq = seq
  elseif not seq and last_seq == nil then
    last_seq = ""                                          -- pas encore de fichier : tout événement sera nouveau
  end
  check_crossing()
  reaper.defer(loop)
end

-- bascule : l'état de l'action (allumée) indique que le lien tourne
local _, _, section, cmd = reaper.get_action_context()
reaper.SetToggleCommandState(section, cmd, 1)
reaper.RefreshToolbar2(section, cmd)
reaper.atexit(function()
  reaper.SetToggleCommandState(section, cmd, 0)
  reaper.RefreshToolbar2(section, cmd)
end)
loop()
