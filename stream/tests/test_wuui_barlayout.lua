-- lua5.1 stream/tests/test_wuui_barlayout.lua stream/fui-web/Interface/AddOns/WrathUnleashedUI/BarLayout.lua
-- The bottom-left and bottom-right bars sit side by side in one row above the main bar.
local file = assert(arg[1], "BarLayout.lua")
local pass, fail = 0, 0
local function check(name, ok, extra) if ok then pass = pass + 1 else fail = fail + 1 end
  print((ok and "PASS " or "FAIL ") .. name .. (extra and ("  " .. tostring(extra)) or "")) end
local function frame(w) local f = { w = w, scripts = {} }
  function f:GetWidth() return self.w end; function f:GetEffectiveScale() return 1 end
  function f:GetLeft() return self.left end; function f:IsShown() return true end
  function f:RegisterEvent() end; function f:SetScript(k, fn) self.scripts[k] = fn end
  function f:Hide() end; function f:HookScript() end
  return f end
UIParent = frame(1227); function UIParent:GetEffectiveScale() return 1 end
_G.ForeverUIActionBarHolder = frame(1115); ForeverUIActionBarHolder.left = 48
local created = {}
function CreateFrame() local fr = frame(0); created[#created + 1] = fr; return fr end
function InCombatLockdown() return false end
function UnitClass() return "Warrior", "WARRIOR" end; function UnitLevel() return 80 end
local defaults, restacked = {}, 0
local fuiLift = 0
ForeverUI = { MultiBars = { bars = { { id = "bl", frame = frame(560) }, { id = "br", frame = frame(560) }, { id = "r1" }, { id = "r2" } },
  Restack = function() restacked = restacked + 1 end, Lift = function() fuiLift = fuiLift + 1; return 49 end },
  Layout = { SetDefaults = function(id, p, rp, x, y) defaults[id] = { x, y } end, IsDefault = function() return true end } }
dofile(file)
check("apply runs", WrathUnleashedUI.FixBars() == true)
local M = ForeverUI.MultiBars
local b1, b2 = M.bars[1], M.bars[2]
check("bar 1 starts at the main bar's left edge", b1.x == 48 - 1227 / 2, b1.x)
check("bar 2 right after bar 1 (same row)", b2.y == b1.y and b2.x == b1.x + 560 + 6, b2.x)
check("one row just above the main bar", b1.y == 70, b1.y)
check("bar 2 ends inside the screen", b2.x + 560 <= 1227 / 2, b2.x + 560)
check("defaults saved for both", defaults.bl and defaults.br and defaults.br[1] == b2.x)
check("lift is one row", M.Lift() == 49, M.Lift())
check("restacked", restacked == 1)

-- In a vehicle Forever UI's own Lift answers (it keeps the last height while the client hides the bottom bars).
ForeverUI.VehicleArt = true
M.bars[1].frame.IsShown = function() return false end; M.bars[2].frame.IsShown = function() return false end
check("vehicle: Forever UI's lift (the last height), not 0", M.Lift() == 49 and fuiLift == 1, M.Lift())
ForeverUI.VehicleArt = nil
check("out of the vehicle, bars hidden: no lift", M.Lift() == 0)
M.bars[1].frame.IsShown = function() return true end; M.bars[2].frame.IsShown = function() return true end

-- The main bar not measurable yet (a slow first load): tried again until it is.
local ev = created[1]
local function run(sec) for _ = 1, sec * 10 do if ev.scripts.OnUpdate then ev.scripts.OnUpdate(ev, 0.1) end end end
ForeverUIActionBarHolder.left = nil
M.bars[1].x, M.bars[1].y = 0, 0
ev.scripts.OnEvent(ev, "PLAYER_ENTERING_WORLD")
run(2)
check("not measurable: nothing placed yet", M.bars[1].x == 0)
check("not measurable: still trying", ev.scripts.OnUpdate ~= nil)
ForeverUIActionBarHolder.left = 48
run(2)
check("measurable later: placed", M.bars[1].x == 48 - 1227 / 2, M.bars[1].x)
check("placed: no more tries", ev.scripts.OnUpdate == nil)
ForeverUIActionBarHolder.left = nil
ev.scripts.OnEvent(ev, "DISPLAY_SIZE_CHANGED")
run(30)
check("never measurable: gives up after a few tries", ev.scripts.OnUpdate == nil)
ForeverUIActionBarHolder.left = 48

-- In combat: after the fight.
local combat = true
InCombatLockdown = function() return combat end
M.bars[1].x = 0
ev.scripts.OnEvent(ev, "PLAYER_LEVEL_UP"); run(2)
check("combat: nothing moved", M.bars[1].x == 0)
ev.scripts.OnEvent(ev, "PLAYER_REGEN_ENABLED"); combat = false; run(2)
check("after the fight: placed", M.bars[1].x == 48 - 1227 / 2)
print(("\n%d/%d passed"):format(pass, pass + fail)); os.exit(fail == 0 and 0 or 1)
