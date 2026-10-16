-- Premier démarrage du REAPER LV1 (portable, installé par LV1 Suite) — xtouch-lv1-bridge, 16/10/2026.
-- Lancé par __startup.lua ; ne fait son travail QU'UNE fois (ExtState lv1_suite/firstrun), ensuite rien : Joseph
-- peaufine la présentation à la main et ses réglages sont gardés.
-- Vue façon Tracks Live 2 : pistes seulement (table de mixage et piste master cachées), barre de transport en haut,
-- règle en minutes:secondes. Le reste est posé par l'installeur : barre de vumètres (lv1_meter_bridge) ancrée dans le
-- docker du haut, projet type « LV1 Multitrack » (prises dans « Audio ») ouvert pour tout nouveau projet.
-- Les actions sont cherchées par leur NOM (relevés dans REAPER 7.82). Lancées un peu APRÈS le démarrage (essai du
-- 16/10 : pendant __startup.lua, « transport docked to top » restait sans effet).

local EXT = "lv1_suite"
if reaper.GetExtState(EXT, "firstrun") == "done" then return end

local function apply()
  local names = {}
  local i = 0
  while true do
    local id, name = reaper.kbd_enumerateActions(0, i)
    if not id or id == 0 then break end
    names[name:lower()] = id                    -- casse ignorée (« Show transport… » : S majuscule)
    i = i + 1
  end
  local function run(name)
    local id = names[name:lower()]
    if id then reaper.Main_OnCommand(id, 0) end
  end
  local function set_toggle(name, on)            -- action bascule : la mettre dans l'état voulu
    local id = names[name:lower()]
    if id and (reaper.GetToggleCommandState(id) == 1) ~= on then reaper.Main_OnCommand(id, 0) end
  end

  set_toggle("View: Toggle Mixer visible", false)
  reaper.SetMasterTrackVisibility(reaper.GetMasterTrackVisibility() & ~1)
  set_toggle("View: Toggle transport visible (Play/Record/Stop...)", true)
  run("Transport: show transport docked to top of main window")
  run("View: Time unit for ruler: Minutes:Seconds")
  reaper.SetExtState(EXT, "firstrun", "done", true)
end

local wait = 30                                    -- ~1 s de cycles defer : fenêtre principale prête
local function later()
  wait = wait - 1
  if wait > 0 then reaper.defer(later) else apply() end
end
later()
