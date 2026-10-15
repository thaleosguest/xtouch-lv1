-- Barre de vumètres façon Tracks Live 2 (« Meter Bridge ») pour Reaper — xtouch-lv1-bridge, demande de Joseph du
-- 16/10/2026 : Reaper réduit aux pistes + vumètres, comme Tracks Live 2.
--   * une colonne par piste : n° (canal LV1 si la piste est synchronisée, sinon n° de piste), couleur, nom court,
--     vumètre (2 barres si stéréo), maintien de crête 1,5 s, voyant rouge d'écrêtage (clic = effacer), « R » si armée ;
--   * ÉCRAN TACTILE (Joseph, 16/10) : gros boutons, pas de clic droit nécessaire (bouton MENU), colonnes larges,
--     glisser le doigt sur les vumètres = défiler ; FIT = toutes les colonnes tiennent dans la fenêtre ;
--   * à gauche : ARM ALL (tout armer / tout désarmer) et MON (monitoring d'entrée de toutes les pistes, OFF -> ON ->
--     AUTO) ; W - / W + = hauteur des formes d'onde (zoom d'amplitude, affichage seulement) ; « R » en bas d'une colonne = armer cette piste (demande de Joseph du 16/10) ;
--   * clic sur une colonne = sélectionne la piste et la fait défiler dans la vue ;
--   * MENU (ou clic droit) : afficher/cacher la table de mixage et la piste master (vue « pistes seulement »), hauteur de toutes
--     les pistes (comme le sélecteur « Micro » de Tracks Live), pistes LV1 seulement, ancrer / détacher.
-- Les vumètres sont ceux de Reaper (Track_GetPeakInfo) : piste armée = niveau d'ENTRÉE si l'option de Reaper
-- « afficher l'entrée des pistes armées » est active (à vérifier chez Joseph).
-- Textes à l'écran en ANGLAIS (demande de Joseph).
--
-- Installation : Actions > Show action list > New action > Load ReaScript… > ce fichier, puis Run. Fenêtre ancrée
-- par défaut dans le docker ; clic droit sur l'onglet du docker > « Attach docker to: Top » pour la mettre en haut
-- comme dans Tracks Live. Relancer l'action la ferme (bascule).

local EXT = "lv1_meter_bridge"
local DB_MIN, DB_MAX = -60, 0           -- échelle : barre pleine = 0 dBFS (comme Tracks Live)
local HOLD, FALL = 1.5, 30              -- maintien de crête (s), retombée du vumètre (dB/s)
local COL_W, COL_MIN = 44, 10           -- largeur fixe d'une colonne / minimum en mode « tout voir »
local BTN_W, BTN_H = 70, 40             -- boutons tactiles (2 colonnes x 3 rangées) à gauche, puis l'échelle
local PANEL_W = 3 * 4 + 2 * BTN_W
local HEAD_H, FOOT_H, SIDE_W = 34, 28, PANEL_W + 22
local DRAG_MIN = 10                     -- px : au-delà, un doigt posé sur les vumètres fait défiler (pas de clic)
local MON_MODES = {{0, "OFF"}, {1, "ON"}, {2, "AUTO"}}  -- I_RECMON : 0 off, 1 entrée, 2 auto (« tape auto style »)
local HEIGHTS = {{"Micro", 24}, {"Small", 40}, {"Medium", 64}, {"Large", 100}, {"Extreme", 160}}
local TICKS = {0, -6, -12, -18, -30, -42, -60}

local BG = {0.086, 0.094, 0.106}
local STRIP = {0.149, 0.161, 0.176}
local TEXT = {0.88, 0.90, 0.92}
local DIM = {0.45, 0.47, 0.50}

local fit = reaper.GetExtState(EXT, "fit") == "1"
local lv1_only = reaper.GetExtState(EXT, "lv1_only") == "1"
local scroll = 0
local meters = {}                       -- GUID -> {lvl = {dB, dB}, peak = {dB, dB}, peak_t = {t, t}, clip = bool}
local cols = {}                         -- colonnes dessinées : {x, w, tr}
local last_t = reaper.time_precise()
local mouse_was = 0
local press = nil                       -- doigt posé sur les colonnes : {x, y, scroll, drag}

local function db_of(v)
  if v <= 0 then return -150 end
  return 20 * math.log(v, 10)
end

local function frac(db)                 -- 0..1 de bas en haut
  return math.max(0, math.min(1, (db - DB_MIN) / (DB_MAX - DB_MIN)))
end

local function set(c, a) gfx.set(c[1], c[2], c[3], a or 1) end

local function tracks()
  local list = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, tag = reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_in", "", false)
    if reaper.GetMediaTrackInfo_Value(tr, "B_SHOWINTCP") == 1 and (not lv1_only or tag ~= "") then
      local _, st = reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:lv1_stereo", "", false)
      local nch = reaper.GetMediaTrackInfo_Value(tr, "I_NCHAN")
      list[#list + 1] = {tr = tr, num = tag ~= "" and (tonumber(tag) + 1) or (i + 1),
                         stereo = (st == "1") or (st == "" and nch >= 2)}
    end
  end
  return list
end

local function update_meter(t, now, dt)
  local guid = reaper.GetTrackGUID(t.tr)
  local m = meters[guid]
  if not m then
    m = {lvl = {-150, -150}, peak = {-150, -150}, peak_t = {0, 0}, clip = false}
    meters[guid] = m
  end
  for c = 1, 2 do
    local db = db_of(reaper.Track_GetPeakInfo(t.tr, c - 1))
    m.lvl[c] = math.max(db, m.lvl[c] - FALL * dt)
    if db >= m.peak[c] or now - m.peak_t[c] > HOLD then m.peak[c], m.peak_t[c] = db, now end
    if db >= 0 then m.clip = true end
  end
  return m
end

local function draw_bar(x, y, w, h, db, peak)
  set({0.06, 0.065, 0.07})
  gfx.rect(x, y, w, h, 1)
  local zones = {{-150, -18, {0.23, 0.82, 0.42}}, {-18, -6, {0.93, 0.85, 0.25}}, {-6, 1, {0.95, 0.35, 0.22}}}
  for _, z in ipairs(zones) do
    local lo, hi = frac(math.max(z[1], DB_MIN)), frac(math.min(z[2], db))
    if hi > lo then
      set(z[3])
      local y1, y0 = y + h - math.floor(hi * h), y + h - math.floor(lo * h)
      gfx.rect(x, y1, w, y0 - y1, 1)
    end
  end
  if peak > DB_MIN then
    set(peak >= -6 and {0.95, 0.35, 0.22} or TEXT)
    gfx.rect(x, y + h - math.floor(frac(peak) * h), w, 2, 1)
  end
end

local function fit_text(s, w)
  if gfx.measurestr(s) <= w then return s end
  while #s > 1 and gfx.measurestr(s) > w do s = s:sub(1, -2) end
  return s
end

local function draw_column(t, m, x, w, top, bottom)
  local tr = t.tr
  local color = reaper.GetTrackColor(tr)
  local sel = reaper.IsTrackSelected(tr)
  set(sel and {0.25, 0.27, 0.30} or STRIP)
  gfx.rect(x, 0, w - 1, gfx.h, 1)
  if color ~= 0 then                                       -- bandeau de couleur de la piste
    local r, g, b = reaper.ColorFromNative(color)
    gfx.set(r / 255, g / 255, b / 255, 1)
    gfx.rect(x, 0, w - 1, 4, 1)
  end
  gfx.setfont(1)
  set(TEXT)
  local num = tostring(t.num)
  gfx.x, gfx.y = x + math.floor((w - 1 - gfx.measurestr(num)) / 2), 6
  gfx.drawstr(num)
  gfx.setfont(2)
  set(DIM)
  local _, name = reaper.GetTrackName(tr)
  name = fit_text(name, w - 3)
  gfx.x, gfx.y = x + math.floor((w - 1 - gfx.measurestr(name)) / 2), 20
  gfx.drawstr(name)
  if m.clip then                                           -- voyant d'écrêtage, reste allumé jusqu'au clic
    gfx.set(0.95, 0.15, 0.12, 1)
    gfx.rect(x + 2, top - 5, w - 5, 3, 1)
  end
  local h = bottom - top
  local inner = w - 5
  if t.stereo and inner >= 5 then
    local bw = math.floor((inner - 1) / 2)
    draw_bar(x + 2, top, bw, h, m.lvl[1], m.peak[1])
    draw_bar(x + 3 + bw, top, inner - 1 - bw, h, m.lvl[2], m.peak[2])
  else
    draw_bar(x + 2, top, inner, h, m.lvl[1], m.peak[1])
  end
  do                                                       -- R : case rouge si armée, grise sinon (toucher = armer)
    local armed = reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") == 1
    if armed then gfx.set(0.95, 0.2, 0.18, 1) else set({0.22, 0.24, 0.27}) end
    gfx.rect(x + 2, bottom + 3, w - 5, FOOT_H - 5, 1)
    if armed then gfx.set(0.05, 0.05, 0.05, 1) else set(DIM) end
    gfx.setfont(1)
    gfx.x, gfx.y = x + math.floor((w - 1 - gfx.measurestr("R")) / 2), bottom + 3 + math.floor((FOOT_H - 5 - gfx.texth) / 2)
    gfx.drawstr("R")
  end
end

local function draw_scale(top, bottom)
  set(BG)
  gfx.rect(0, 0, SIDE_W, gfx.h, 1)
  gfx.setfont(2)
  for _, db in ipairs(TICKS) do
    local y = bottom - math.floor(frac(db) * (bottom - top))
    set(DIM)
    local s = tostring(-db)
    gfx.x, gfx.y = SIDE_W - 3 - gfx.measurestr(s), y - 5
    gfx.drawstr(s)
  end
end

-- Hauteur des formes d'onde (comme le zoom d'amplitude de Tracks Live) : actions « View: Increase / Decrease peaks
-- view gain », cherchées par leur NOM dans la liste d'actions (n° non vérifiés de mémoire).
local function find_action(words)
  if not reaper.kbd_enumerateActions then return nil end
  local i = 0
  while true do
    local id, name = reaper.kbd_enumerateActions(0, i)
    if not id or id == 0 then return nil end
    local low = name:lower()
    local all = true
    for _, w in ipairs(words) do if not low:find(w, 1, true) then all = false end end
    if all then return id end
    i = i + 1
  end
end
local WAVE_UP = find_action({"increase", "peaks view gain"})
local WAVE_DOWN = find_action({"decrease", "peaks view gain"})

local buttons = {}                      -- boutons globaux dessinés : {x, y, w, h, act}

-- État commun des pistes affichées : true / false si toutes pareilles, nil si mélangé
local function common(list, key)
  local v = nil
  for i, t in ipairs(list) do
    local x = math.floor(reaper.GetMediaTrackInfo_Value(t.tr, key))
    if i == 1 then v = x elseif v ~= x then return nil end
  end
  return v
end

local function button(x, y, w, h, label, on, act, color)
  set(on and (color or {0.95, 0.2, 0.18}) or {0.22, 0.24, 0.27})
  gfx.rect(x, y, w, h, 1)
  set(on and {0.05, 0.05, 0.05} or TEXT)
  gfx.setfont(1)
  gfx.x, gfx.y = x + math.floor((w - gfx.measurestr(label)) / 2), y + math.floor((h - gfx.texth) / 2)
  gfx.drawstr(label)
  buttons[#buttons + 1] = {x = x, y = y, w = w, h = h, act = act}
end

local function draw_panel(list)
  buttons = {}
  local bh = math.max(24, math.min(BTN_H, math.floor((gfx.h - 6) / 3) - 4))   -- fenêtre basse : boutons réduits
  local x1, x2 = 4, 8 + BTN_W
  local row = function(k) return 6 + k * (bh + 4) end
  local arm = common(list, "I_RECARM")
  button(x1, row(0), BTN_W, bh, arm == 1 and "ARMED" or "ARM ALL", arm == 1, "arm")
  local mon = common(list, "I_RECMON")
  local label = "MON ?"
  for _, m in ipairs(MON_MODES) do if mon == m[1] then label = "MON " .. m[2] end end
  if #list == 0 then label = "MON" end
  button(x2, row(0), BTN_W, bh, label, mon == 1 or mon == 2, "mon", {0.95, 0.75, 0.2})
  button(x1, row(1), BTN_W, bh, WAVE_DOWN and "WAVE -" or "?", false, "wave_down")
  button(x2, row(1), BTN_W, bh, WAVE_UP and "WAVE +" or "?", false, "wave_up")
  button(x1, row(2), BTN_W, bh, "FIT", fit, "fit", {0.22, 0.79, 1.0})
  button(x2, row(2), BTN_W, bh, "MENU", false, "menu")
end

local function draw()
  local now = reaper.time_precise()
  local dt = math.min(0.2, now - last_t)
  last_t = now
  set(BG)
  gfx.rect(0, 0, gfx.w, gfx.h, 1)
  local list = tracks()
  local top, bottom = HEAD_H + 6, gfx.h - FOOT_H
  local area = gfx.w - SIDE_W
  local w = COL_W
  if fit and #list > 0 then w = math.max(COL_MIN, math.floor(area / #list)) end
  local max_scroll = math.max(0, #list * w - area)
  scroll = math.max(0, math.min(scroll, max_scroll))
  cols = {}
  for i, t in ipairs(list) do
    local m = update_meter(t, now, dt)
    local x = SIDE_W + (i - 1) * w - scroll
    if x + w > SIDE_W and x < SIDE_W + area then
      draw_column(t, m, x, w, top, bottom)
      cols[#cols + 1] = {x = x, w = w, tr = t.tr, m = m}
    end
  end
  for _, db in ipairs(TICKS) do                            -- repères en travers des vumètres
    gfx.set(0, 0, 0, 0.35)
    gfx.line(SIDE_W, bottom - math.floor(frac(db) * (bottom - top)), SIDE_W + area, bottom - math.floor(frac(db) * (bottom - top)))
  end
  draw_scale(top, bottom)
  draw_panel(list)
  if #list == 0 then
    set(DIM); gfx.setfont(1)
    gfx.x, gfx.y = SIDE_W + 8, top
    gfx.drawstr(lv1_only and "No LV1 track (run LV1 sync tracks)" or "No track")
  end
  return max_scroll
end

local function set_heights(h)
  for i = 0, reaper.CountTracks(0) - 1 do
    reaper.SetMediaTrackInfo_Value(reaper.GetTrack(0, i), "I_HEIGHTOVERRIDE", h)
  end
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
end

local function menu()
  local mixer = reaper.GetToggleCommandState(40078) == 1              -- View: Toggle mixer visible
  local master = reaper.GetMasterTrackVisibility() & 1 == 1
  local items = {(mixer and "!" or "") .. "Show mixer", (master and "!" or "") .. "Show master track", ""}
  for _, h in ipairs(HEIGHTS) do items[#items + 1] = "Track height: " .. h[1] end
  items[#items + 1] = ""
  items[#items + 1] = (lv1_only and "!" or "") .. "LV1 tracks only"
  items[#items + 1] = (fit and "!" or "") .. "Fit all channels"
  items[#items + 1] = "Clear clip indicators"
  items[#items + 1] = (gfx.dock(-1) & 1 == 1) and "Undock" or "Dock"
  gfx.x, gfx.y = gfx.mouse_x, gfx.mouse_y
  local k = gfx.showmenu(table.concat(items, "|"))
  local n = #HEIGHTS
  if k == 1 then reaper.Main_OnCommand(40078, 0)
  elseif k == 2 then reaper.SetMasterTrackVisibility(reaper.GetMasterTrackVisibility() ~ 1)
  elseif k >= 3 and k < 3 + n then set_heights(HEIGHTS[k - 2][2])
  elseif k == 3 + n then lv1_only = not lv1_only; reaper.SetExtState(EXT, "lv1_only", lv1_only and "1" or "0", true)
  elseif k == 4 + n then fit = not fit; reaper.SetExtState(EXT, "fit", fit and "1" or "0", true)
  elseif k == 5 + n then for _, m in pairs(meters) do m.clip = false end
  elseif k == 6 + n then gfx.dock((gfx.dock(-1) & 1 == 1) and 0 or 1)
  end
end

local function set_all(list, key, v, what)
  reaper.Undo_BeginBlock()
  for _, t in ipairs(list) do reaper.SetMediaTrackInfo_Value(t.tr, key, v) end
  reaper.Undo_EndBlock("LV1 bridge: " .. what, -1)
end

local function click(x, y)                                 -- boutons : dès l'appui
  for _, b in ipairs(buttons) do
    if x >= b.x and x < b.x + b.w and y >= b.y and y < b.y + b.h then
      local list = tracks()
      if b.act == "menu" then menu()
      elseif b.act == "fit" then
        fit = not fit
        reaper.SetExtState(EXT, "fit", fit and "1" or "0", true)
      elseif b.act == "wave_up" or b.act == "wave_down" then  -- hauteur des formes d'onde
        local id = b.act == "wave_up" and WAVE_UP or WAVE_DOWN
        if id then reaper.Main_OnCommand(id, 0)
        else reaper.ShowConsoleMsg("LV1 Meter Bridge: action 'peaks view gain' not found\n") end
      elseif b.act == "arm" then                               -- tout armé -> tout désarmer, sinon tout armer
        local on = common(list, "I_RECARM") == 1
        set_all(list, "I_RECARM", on and 0 or 1, on and "disarm all" or "arm all")
      else                                                 -- OFF -> ON -> AUTO -> OFF (mélangé -> OFF)
        local mon, nxt = common(list, "I_RECMON"), 0
        if mon == 0 then nxt = 1 elseif mon == 1 then nxt = 2 end
        set_all(list, "I_RECMON", nxt, "monitoring " .. MON_MODES[nxt + 1][2])
      end
      return
    end
  end
end

local function tap(x, y)                                   -- doigt levé sans glisser sur une colonne
  for _, c in ipairs(cols) do
    if x >= c.x and x < c.x + c.w then
      if c.m.clip and y < HEAD_H + 6 then c.m.clip = false return end
      if y >= gfx.h - FOOT_H then                          -- R de la colonne = armer / désarmer cette piste
        local arm = reaper.GetMediaTrackInfo_Value(c.tr, "I_RECARM") == 1 and 0 or 1
        reaper.SetMediaTrackInfo_Value(c.tr, "I_RECARM", arm)
        return
      end
      reaper.SetOnlyTrackSelected(c.tr)
      reaper.Main_OnCommand(40913, 0)                       -- Track: Vertical scroll selected tracks into view
      return
    end
  end
end

local function loop()
  local max_scroll = draw()
  local cap = gfx.mouse_cap
  local mx, my = gfx.mouse_x, gfx.mouse_y
  if cap & 1 == 1 and mouse_was & 1 == 0 then
    if mx < SIDE_W then click(mx, my) else press = {x = mx, y = my, scroll = scroll, drag = false} end
  elseif cap & 1 == 1 and press then                       -- glisser = défiler (largeur fixe)
    if math.abs(mx - press.x) > DRAG_MIN then press.drag = true end
    if press.drag then scroll = math.max(0, math.min(max_scroll, press.scroll - (mx - press.x))) end
  elseif cap & 1 == 0 and press then
    if not press.drag then tap(press.x, press.y) end
    press = nil
  end
  if cap & 2 == 2 and mouse_was & 2 == 0 then menu() end
  mouse_was = cap
  if gfx.mouse_wheel ~= 0 then
    scroll = math.max(0, math.min(max_scroll, scroll - gfx.mouse_wheel / 120 * COL_W))
    gfx.mouse_wheel = 0
  end
  gfx.update()
  if gfx.getchar() >= 0 then reaper.defer(loop) end
end

local _, _, section, cmd = reaper.get_action_context()
reaper.SetToggleCommandState(section, cmd, 1)
reaper.RefreshToolbar2(section, cmd)
reaper.atexit(function()
  reaper.SetExtState(EXT, "dock", tostring(gfx.dock(-1)), true)
  reaper.SetToggleCommandState(section, cmd, 0)
  reaper.RefreshToolbar2(section, cmd)
  gfx.quit()
end)

local dock = tonumber(reaper.GetExtState(EXT, "dock")) or 1
gfx.init("LV1 Meter Bridge", 900, 220, dock)
gfx.setfont(1, "Segoe UI", 14, string.byte("b"))
gfx.setfont(2, "Segoe UI", 12)
loop()
