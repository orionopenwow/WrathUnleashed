-- lua5.1 stream/tests/test_wuui_builder.lua [addon dir] [ov_build.lua] [ov_modapi.lua]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order, opens the Builder window from
-- Esc > Mods & Workshop, and runs real round trips through ov_build.lua and ov_modapi.lua (fake mod-ale):
-- the catalog over OVMOD, search and categories, Spawn, the nudges and turns, Undo, Delete, Save / Share / Load
-- with the code box, "isn't on this realm" without the script, and no game-brand names on screen. M3: the budget
-- meter and blocked spawns, the spawn menu (tabs, search, recent, favourites, prefabs), the properties panel,
-- the group / prefab / plot rows, and edit mode's paste, box select, Shift-click, prefab and hold-Q hooks. 2026-10-30:
-- redo, put away and the Storage tab, and the Den panel (info, the invite link to copy, builders, layouts).
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local server = arg[2] or "realm/custom/lua_scripts/ov_build.lua"
local modapi = arg[3] or server:gsub("ov_build%.lua$", "ov_modapi.lua")

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_leyline.lua)
local frames, created = {}, {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end -- other widget methods: no-ops
    return nil
end
function Frame:SetScript(n, fn) self.scripts[n] = fn end
function Frame:GetScript(n) return self.scripts[n] end
function Frame:Fire(n, ...) local fn = self.scripts[n]; if fn then return fn(self, ...) end end
function Frame:Show()
    local was = self:IsVisible(); self.shown = true
    if not was and self:IsVisible() then self:Fire("OnShow") end
end
function Frame:Hide()
    local was = self:IsVisible(); self.shown = false
    if was then self:Fire("OnHide") end
end
function Frame:IsShown() return self.shown end
function Frame:IsVisible()
    if not self.shown then return false end
    return self.parent == nil or self.parent.top or self.parent:IsVisible()
end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:Enable() self.enabled = true end
function Frame:Disable() self.enabled = false end
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:UnregisterEvent(e) self.events[e] = nil end
function Frame:GetName() return self.name end
function Frame:GetParent() return self.parent end
function Frame:GetHeight() return self.h or 0 end
function Frame:SetHeight(h) self.h = h end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent, template)
    local f = new(kind, name, parent); frames[#frames + 1] = f
    if template == "OptionsSliderTemplate" and name then
        new("FontString", name .. "Low", f); new("FontString", name .. "High", f)
    end
    return f
end

UIParent = new("Frame", "UIParent"); UIParent.top = true
function UIParent:GetScale() return 1 end
GameMenuFrame = new("Frame", "GameMenuFrame"); GameMenuFrame.top = true; GameMenuFrame.h = 300
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
function GetScreenHeight() return 981 end
function InCombatLockdown() return false end
function SetBinding() return 1 end
function SetBindingClick() return 1 end
function SaveBindings() end
function SetCVar() end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function UnitName() return "Tester" end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end

-- ---------------------------------------------------------------- the realm (ov_build.lua + ov_modapi.lua, fake mod-ale)
local realGetenv, realTime = os.getenv, os.time
local serverClock = 1000000
os.time = function() return serverClock end
os.getenv = function() return nil end
local onServerAddon
function RegisterServerEvent(id, fn) if id == 30 then onServerAddon = fn end end
function RegisterPlayerEvent() end
function CreateLuaEvent() end
function CharDBExecute() end
function CharDBQuery() return nil end
local objects, nextGuid = {}, 1
local map0 = { GetWorldObject = function(_, g) return objects[g] end }
function PerformIngameSpawn(kind, entry, map, inst, x, y, z, o, save)
    nextGuid = nextGuid + 1
    local go = { guid = nextGuid, entry = entry, x = x, y = y, z = z, o = o }
    function go:GetGUID() return self.guid end
    function go:RemoveFromWorld() objects[self.guid] = nil end
    function go:SetScale(sc) self.scale = sc end
    objects[go.guid] = go
    return go
end
function GetGUIDLow(g) return g end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local chat = {}
local player = { x = -9448.55, y = 68.24, z = 56.32, o = 0 }
function player:GetGUIDLow() return 7 end
function player:GetName() return "Tester" end
function player:GetGMRank() return 1 end
function player:GetMapId() return 0 end
function player:GetMap() return map0 end
function player:GetX() return self.x end
function player:GetY() return self.y end
function player:GetZ() return self.z end
function player:GetO() return self.o end
function player:SendBroadcastMessage(m) chat[#chat + 1] = m end
function player:SendAddonMessage(prefix, msg) fireClient(prefix, msg, "WHISPER", "Tester") end
package.preload["ov_modapi"] = function() return dofile(modapi) end
dofile(server)
local T = assert(OV_BUILD_TEST)
os.getenv = realGetenv

local sent = {}
function SendAddonMessage(prefix, msg, channel, target)
    sent[#sent + 1] = { prefix, msg, channel, target }
    if target == UnitName("player") and onServerAddon then onServerAddon(30, player, 7, prefix, msg, player) end
end

-- ---------------------------------------------------------------- load the addon in .toc order
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
local at = {}
for i, f in ipairs(files) do at[f] = i end
check(".toc lists Builder.lua (before Leyline.lua)", at["Builder.lua"] and at["Builder.lua"] < at["Leyline.lua"])
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local B = assert(W.Builder, "W.Builder")
check("builds nothing until opened", B.Window() == nil)
check("/builder", SLASH_WUBUILDER1 == "/builder" and SlashCmdList.WUBUILDER)

-- Esc > Mods & Workshop > Builder
GameMenuButtonAddOns:Fire("OnClick")
local mods = _G.WrathUnleashedModsFrame
local open
for _, f in ipairs(created) do if f.parent == mods and f.text == "Builder" then open = f end end
check("Mods & Workshop has a Builder button", mods and mods:IsShown() and open)
open:Fire("OnClick")
local win = B.Window()
check("it opens the Builder window and closes the panel", win and win:IsShown() and not mods:IsShown())
check("Esc closes it", UISpecialFrames[#UISpecialFrames] == "WrathUnleashedBuilderFrame")
check("asked for the catalog over OVMOD, whispered to self", sent[1] and sent[1][1] == "OVMOD" and sent[1][2] == "wubuild\tcatalog\t1/1\t"
    and sent[1][3] == "WHISPER" and sent[1][4] == "Tester")

local function shown()
    local out = {}
    for _, r in ipairs(win.rows) do if r:IsShown() then out[#out + 1] = r end end
    return out
end
check("the catalog arrives: a page of rows", #B.catalog == #T.CATALOG() and #shown() == #win.rows and win.count:GetText():find("of " .. #B.catalog))
check("state arrived: not selected, in Goldshire green", win.sel:GetText():find("Nothing selected") and win.sel:GetText():find("Goldshire green"))
check("Spawn waits for a pick", win.spawn.enabled == false)

-- search and categories
win.search:SetText("lant"); win.search:Fire("OnTextChanged")
local function countWhere(fn) local n = 0; for _, c in ipairs(T.CATALOG()) do if fn(c) then n = n + 1 end end; return n end
local lanterns = countWhere(function(c) return c.name:lower():find("lant", 1, true) or c.key:find("lant", 1, true) end)
check("search filters", lanterns >= 2 and #shown() == math.min(lanterns, #win.rows) and shown()[1].name:GetText():lower():find("lant"))
win.search:SetText(""); win.search:Fire("OnTextChanged")
win.catBtn:Fire("OnClick")
local seats = countWhere(function(c) return c.cat == "seating" end)
check("category: seating", win.catBtn:GetText() == "Category: seating" and seats >= 5 and #shown() == math.min(seats, #win.rows))
for _ = 1, #B.CATS - 1 do win.catBtn:Fire("OnClick") end
check("categories go round to all", win.catBtn:GetText() == "Category: all")
win.list:Fire("OnMouseWheel", -1)
check("mouse wheel scrolls", B.offset == 1)
win.list:Fire("OnMouseWheel", 1)

-- pick and spawn
shown()[1]:Fire("OnClick")
check("a pick names the Spawn button", win.spawn.enabled and win.spawn:GetText() == "Spawn Wooden Chair")
win.spawn:Fire("OnClick")
local id = T.selected[7]
local p = id and T.props[id]
check("Spawn places it on the realm", p and p.entry == 2413 and objects[T.live[id]])
check("the state shows the selection", win.sel:GetText():find("Selected: Wooden Chair") and win.sel:GetText():find("props 1/50"))
check("the realm said so in chat", chat[#chat]:find("Wooden Chair placed"))

-- nudges and turns
local z0 = p.z
win.nudge["z+"]:Fire("OnClick")
check("z + moves it up one step (1 yd)", math.abs(p.z - (z0 + 1)) < 1e-6 and sent[#sent][2] == "wubuild\tcmd\t1/1\tmove z 1")
win.stepBtn:Fire("OnClick")
win.nudge["x-"]:Fire("OnClick")
check("the step button: 3 yd", win.stepBtn:GetText() == "Step 3 yd" and sent[#sent][2]:find("move x %-3$"))
win.stepBtn:Fire("OnClick")
win.nudge["y+"]:Fire("OnClick")
check("and round to 0.25 yd", sent[#sent][2]:find("move y 0%.25$"))
local o0 = p.o
win.turnL:Fire("OnClick")
check("turn +15 degrees", math.abs(p.o - (o0 + math.rad(15))) < 1e-6)
serverClock = serverClock + 1
win.turnR:Fire("OnClick")
check("turn -15 degrees", math.abs(p.o - o0) < 1e-6)
win.undo:Fire("OnClick")
check("Undo", math.abs(p.o - (o0 + math.rad(15))) < 1e-6 and chat[#chat]:find("Undone"))

-- save / share / load with the box
win.code:SetText("my camp")
win.save:Fire("OnClick")
check("Save takes the name from the box", T.builds[7] and T.builds[7]["mycamp"] and chat[#chat]:find("Saved 'mycamp'"))
win.code:SetText("mycamp")
win.share:Fire("OnClick")
local code = T.builds[7].mycamp.code
check("Share puts the code in the box", code and win.code:GetText() == code)
win.delete:Fire("OnClick")
check("Delete", next(T.props) == nil and win.sel:GetText():find("Nothing selected") and win.sel:GetText():find("props 0/50"))
win.load:Fire("OnClick")
check("Load the code from the box", (function() local n = 0; for _ in pairs(T.props) do n = n + 1 end; return n == 1 end)()
    and chat[#chat]:find("Pasted '" .. code .. "'"))
win.code:SetText("bad|name")
local before = #sent
win.load:Fire("OnClick")
check("a bad name never leaves the window", #sent == before and win.status:GetText():find("Type a build name"))


-- M3: the budget meter ---------------------------------------------------------------------------------------------
local function countProps() local n = 0; for _ in pairs(T.props) do n = n + 1 end; return n end
check("the catalog carries build points", B.catalog[1].cost == T.costOf(B.catalog[1].id))
check("budget meter: props and points", win.meter:GetText():find("Props 1/50") and win.meter:GetText():find("Points %d+/100")
    and B.meterFrac > 0 and B.meterFrac < 0.1)
check("the plot line says there's no plot here", win.plot:GetText():find("No plot here"))
fireClient("OVMOD", "wubuild\tstate\t1/1\tsel=-;mine=50/50;area=Goldshire green;code=-;n=0;pos=-;pts=60/100;tier=builder;plot=-;clip=0", "WHISPER", "Tester")
check("the meter fills at the limit", B.meterFrac == 1)
B.pick = B.catalog[1]
local nSent = #sent
check("Spawn is blocked at the limit, with a plain message", B.Spawn() == false and #sent == nSent
    and win.status:GetText():find("limit of 50 props"))
local heavy
for _, c in ipairs(B.catalog) do if c.cost >= 2 then heavy = c; break end end
fireClient("OVMOD", "wubuild\tstate\t1/1\tsel=-;mine=3/50;area=Goldshire green;code=-;n=0;pos=-;pts=99/100;tier=builder;plot=-;clip=0", "WHISPER", "Tester")
B.pick = heavy
check("and when the points run out", B.Spawn() == false and #sent == nSent and win.status:GetText():find("Not enough build points"))
B.Command("near")   -- the realm's real state again

-- M3: the spawn menu ---------------------------------------------------------------------------------------------
WrathUnleashedUIChar = nil
B.ToggleMenu()
local menu = B.Menu()
check("the spawn menu opens (/spawnmenu too)", menu and menu:IsShown() and SLASH_WUSPAWNMENU1 == "/spawnmenu")
local function cellsShown() local n = 0; for _, c in ipairs(menu.cells) do if c:IsShown() then n = n + 1 end end; return n end
check("All props: a page of the realm's catalog", B.menuTab == "all" and cellsShown() == #menu.cells and menu.cells[1].item == B.catalog[1])
local tabOf = {}
for _, t in ipairs(menu.tabs) do tabOf[t.tab] = t end
check("tabs: favourites, recent, prefabs, storage, all and every category", tabOf.favourites and tabOf.recent and tabOf.prefabs
    and tabOf.storage and tabOf.all and tabOf.seating and tabOf.decor and tabOf.structure and #menu.tabs == 5 + #B.CATS - 1)
tabOf.lights:Fire("OnClick")
check("a category tab", cellsShown() > 0 and (function() for _, c in ipairs(menu.cells) do if c.item and c.item.cat ~= "lights" then return false end end; return true end)())
menu.search:SetText("brazier"); menu.search:Fire("OnTextChanged")
check("search inside the tab", cellsShown() >= 2 and menu.cells[1].item.name:lower():find("brazier"))
menu.search:SetText(""); menu.search:Fire("OnTextChanged")
tabOf.recent:Fire("OnClick")
check("Recent starts empty, and says so", cellsShown() == 0 and menu.empty:GetText():find("show up here"))
tabOf.all:Fire("OnClick")
serverClock = serverClock + 5
local first = menu.cells[1].item
local before = countProps()
menu.cells[1]:Fire("OnClick", "LeftButton")
check("click a prop: it spawns", countProps() == before + 1 and T.props[T.selected[7]].entry == first.id)
check("and goes on the recent list (per character)", WrathUnleashedUIChar.builder.recent[1] == first.id)
tabOf.recent:Fire("OnClick")
check("Recent shows it", menu.cells[1].item == first and cellsShown() == 1)
table.insert(WrathUnleashedUIChar.builder.recent, 999999)
B.MenuRefresh()
check("only props the realm sent are ever listed", cellsShown() == 1)
menu.cells[1]:Fire("OnClick", "RightButton")
check("right-click: a favourite", WrathUnleashedUIChar.builder.favs[first.id] == true and menu.cells[1]:GetText():find("^%* "))
tabOf.favourites:Fire("OnClick")
check("Favourites lists it", cellsShown() == 1 and menu.cells[1].item == first)
menu.cells[1]:Fire("OnClick", "RightButton")
check("right-click again: not a favourite", cellsShown() == 0 and menu.empty:GetText():find("right%-click"))
tabOf.all:Fire("OnClick")
menu.grid:Fire("OnMouseWheel", -1)
check("the wheel scrolls a row", B.menuOffset == 3)
menu:Hide()

-- M3: the properties panel ----------------------------------------------------------------------------------------
win.props:Fire("OnClick")
local panel = B.Panel()
local sp = T.props[T.selected[7]]
check("Properties opens with the selection's numbers", panel and panel:IsShown()
    and tonumber(panel.box.x:GetText()) and math.abs(tonumber(panel.box.x:GetText()) - sp.x) < 0.01
    and panel.box.scale:GetText() == "1.00")
panel.box.x:SetText(string.format("%.2f", sp.x + 2))
panel.box.turn:SetText("180")
serverClock = serverClock + 1
panel.apply:Fire("OnClick")
check("Apply: exact x and facing on the realm", math.abs(sp.x - (player.x + 2)) < 0.02 and math.abs(sp.o - math.pi) < 1e-3
    and panel.box.turn:GetText() == "180")
panel.apply:Fire("OnClick")
check("Apply with nothing changed", panel.status:GetText():find("Nothing changed"))
panel.box.z:SetText("high")
panel.apply:Fire("OnClick")
check("Apply wants numbers", panel.status:GetText():find("Type numbers"))
panel.box.scale:SetText("1.5")
panel.box.z:SetText(string.format("%.2f", sp.z))
serverClock = serverClock + 1
panel.apply:Fire("OnClick")
check("Apply: size", sp.s == 1.5)
panel:Hide()

-- M3: group, copy / paste, prefabs and the plot from the window -------------------------------------------------------
win.selall:Fire("OnClick")
check("Select mine", T.group[7] and #T.group[7] == countProps() and win.sel:GetText():find("Selected: %d props"))
win.copy:Fire("OnClick")
check("Copy", T.clip[7] and #T.clip[7].rel == countProps())
serverClock = serverClock + 10
local n0 = countProps()
win.paste:Fire("OnClick")
check("Paste (outside edit mode: at your feet)", countProps() == n0 * 2)
win.undo:Fire("OnClick")
win.selall:Fire("OnClick")
win.prefab:SetText("porch")
win.prefabSave:Fire("OnClick")
check("Prefab Save: the selection, and the list comes back", #B.prefabs == 1 and B.prefabs[1].name == "porch" and B.prefabs[1].count == n0)
B.ShowMenu(true)
local tabs2 = {}
for _, t in ipairs(menu.tabs) do tabs2[t.tab] = t end
tabs2.prefabs:Fire("OnClick")
check("the spawn menu's Prefabs tab", menu.cells[1].item and menu.cells[1].item.name == "porch" and menu.cells[1]:GetText():find("porch %(" .. n0 .. "%)"))
serverClock = serverClock + 10
menu.cells[1]:Fire("OnClick", "LeftButton")
check("click a prefab: pasted", countProps() == n0 * 2)
win.undo:Fire("OnClick")
menu:Hide()
win.prefab:SetText("porch")
win.prefabShare:Fire("OnClick")
check("Prefab Share: a code in the box", T.prefabs[B.prefabs[1].id].code and win.code:GetText() == T.prefabs[B.prefabs[1].id].code)
win.prefab:SetText("")
nSent = #sent
win.prefabPaste:Fire("OnClick")
check("an empty prefab name never leaves the window", #sent == nSent and win.status:GetText():find("prefab name"))
win.claim:Fire("OnClick")
check("Claim: a plot, shown in the window", next(T.plots) and win.plot:GetText():find("Tester's plot %(yours%)"))
win.plotName:SetText("Nobody")
win.plotAdd:Fire("OnClick")
check("Add sends the name", sent[#sent][2]:find("plot add Nobody$"))

-- M3: edit mode's new clicks (the browser client calls these) ----------------------------------------------------------
local E = W.EditMode
win.selall:Fire("OnClick")
win.copy:Fire("OnClick")
E.StartPasting()
serverClock = serverClock + 10
n0 = countProps()
E.Clicked(player.x + 3, player.y - 3, player.z)
check("edit mode: Paste then a ground click pastes there", countProps() == n0 * 2 and sent[#sent][2]:find("pasteat [%-%d%.]+ [%-%d%.]+ [%-%d%.]+$"))
win.undo:Fire("OnClick")
E.StartBox()
E.Clicked(player.x - 6, player.y - 6, player.z)
check("box select: the first corner waits for the second", E.pending and E.pending.kind == "box" and not sent[#sent][2]:find("selbox"))
E.Clicked(player.x + 6, player.y + 6, player.z)
check("box select: two corners select the box", sent[#sent][2]:find("selbox ") and T.group[7] and #T.group[7] >= 1 and E.pending == nil)
local ids = {}
for id in pairs(T.props) do ids[#ids + 1] = id end
table.sort(ids)
E.Clicked(nil, nil, nil, T.live[ids[1]])
check("a plain click selects just that prop", T.group[7] == nil and T.selected[7] == ids[1])
E.Clicked(nil, nil, nil, T.live[ids[2]], true)
check("Shift-click adds to the selection", sent[#sent][2]:find("pick %d+ add$") and T.group[7] and #T.group[7] == 2)
IsShiftKeyDown = function() return true end
E.Clicked(nil, nil, nil, T.live[ids[2]])
IsShiftKeyDown = nil
check("Shift held (IsShiftKeyDown): takes it out again", T.group[7] == nil and T.selected[7] == ids[1])
E.StartPrefab("porch")
serverClock = serverClock + 10
n0 = countProps()
E.Clicked(player.x - 3, player.y + 3, player.z)
check("a prefab at the clicked point", sent[#sent][2]:find("prefab pasteat porch ") and countProps() > n0)
win.undo:Fire("OnClick")
E.SpawnMenu(true)
check("hold Q: the spawn menu", menu:IsShown())
E.SpawnMenu(false)
check("let go: it closes", not menu:IsShown())

-- Gmod-style edits: the gizmo previews on the client and commits once on release; the panel's tilt -------------------
do
    local function nearly(a, b, eps) return a and b and math.abs(a - b) <= (eps or 0.02) end
    local function lastCmd() return (sent[#sent][2]:match("^wubuild\tcmd\t1/1\t(.*)$")) or "" end
    local calls = {}
    LeylineEdit = function(text) calls[#calls + 1] = text; return "ok" end
    E.Clicked(nil, nil, nil, T.live[ids[1]])
    local pid = T.selected[7]
    local gp = T.props[pid]
    local gid = T.live[pid]
    local function called(text) for _, c in ipairs(calls) do if c == text then return true end end end
    check("gizmo: the state's object ids reach the client (group and handles)", called("group " .. gid) and called("select " .. gid))
    check("gizmo: prop and object ids map both ways", B.PropForObject(gid) == pid and B.ObjectOfProp(pid) == gid and B.PropForObject(424242) == nil)
    E.GizmoStart("ring")
    check("gizmo: a drag start says what it does", E.note:find("Turning"))
    serverClock = serverClock + 1
    local x0, y0, z0, o0 = gp.x, gp.y, gp.z, gp.o
    E.GizmoCommit(gid, 1.5, 0, 0, 0, x0 + 1.5, y0, z0)
    check("gizmo: one prop commits as .build move <id> x y z yaw", lastCmd():find("^move " .. pid .. " [%-%d%.]+ [%-%d%.]+ [%-%d%.]+ [%d%.]+$")
        and nearly(T.props[pid].x, x0 + 1.5) and nearly(T.props[pid].o, o0, 0.01) and E.note:find("Placed"))
    serverClock = serverClock + 1
    gp = T.props[pid]
    E.GizmoCommit(T.live[pid], 0, 0, 0, 90, gp.x, gp.y, gp.z)
    check("gizmo: the ring turns it by the drag", nearly(T.props[pid].o, (o0 + math.pi / 2) % (2 * math.pi), 0.01))
    serverClock = serverClock + 1
    E.GizmoCommit(424242, 0, 1, 0, 0, gp.x, gp.y + 1, gp.z)
    check("gizmo: an object the state doesn't know goes the carry way (placeat)", lastCmd():find("^placeat "))
    -- a group dragged by a member that isn't the last-picked one
    E.Clicked(nil, nil, nil, T.live[ids[1]])
    E.Clicked(nil, nil, nil, T.live[ids[2]], true)
    local a, b = T.props[ids[1]], T.props[ids[2]]
    local ay, by = a.y, b.y
    serverClock = serverClock + 1
    E.GizmoCommit(T.live[ids[1]], 0, 2, 0, 0, a.x, a.y + 2, a.z)
    check("gizmo: a group moves together by the drag's delta", lastCmd():find("^placeat ") and nearly(a.y, ay + 2) and nearly(b.y, by + 2))

    -- the properties panel: one prop goes as one move; tilt without the module is said
    E.Clicked(nil, nil, nil, T.live[ids[1]])
    pid = T.selected[7]
    gp = T.props[pid]
    B.ShowProps(true)
    check("panel: pitch and roll boxes", panel.box.pitch and panel.box.roll and panel.box.pitch:GetText() == "0" and panel.box.roll:GetText() == "0")
    panel.box.x:SetText(string.format("%.2f", gp.x + 1))
    serverClock = serverClock + 1
    local nChat = #chat
    panel.apply:Fire("OnClick")
    check("panel: one prop's numbers go as one .build move <id>", lastCmd():find("^move " .. pid .. " ") and nearly(gp.x, T.props[pid].x))
    panel.box.pitch:SetText("10")
    serverClock = serverClock + 1
    panel.apply:Fire("OnClick")
    check("panel: no module, tilt is said and not kept", gp.pt == nil and panel.status:GetText():find("Tilt needs a realm update")
        and chat[#chat]:find("tilting needs a realm update"))
    panel.box.pitch:SetText("400")
    panel.apply:Fire("OnClick")
    check("panel: tilt limits", panel.status:GetText():find("from %-180 to 180"))

    -- with mod-sandbox-core (a fake that keeps GUIDs)
    local function newObj(entry, x, y, z, size)
        nextGuid = nextGuid + 1
        local go = { guid = nextGuid, entry = entry, x = x, y = y, z = z, size = size, core = true }
        function go:GetGUID() return self.guid end
        function go:RemoveFromWorld() objects[self.guid] = nil end
        objects[go.guid] = go
        return go
    end
    Sandbox = {
        Available = function() return true end,
        Spawn = function(_, entry, _, x, y, z, _, _, _, _, size) return newObj(entry, x, y, z, size).guid end,
        Move = function(g, x, y, z) local go = objects[g]; if not go or not go.core then return nil end; go.x, go.y, go.z = x, y, z; return g end,
        SetScale = function(g, size) local go = objects[g]; if not go then return nil end; go.size = size; return true end,
        Despawn = function(g) objects[g] = nil; return true end,
    }
    panel.box.pitch:SetText("10")
    serverClock = serverClock + 1
    panel.apply:Fire("OnClick")
    local g1 = T.live[pid]
    check("panel with the module: tilt kept, the prop now the module's", nearly(T.props[pid].pt, math.rad(10), 1e-3) and objects[g1] and objects[g1].core
        and B.state.core and nearly(B.state.p.pitch, 10, 0.05))
    check("the handles follow the prop's new object id", called("select " .. g1))
    panel.box.roll:SetText("-5")
    serverClock = serverClock + 1
    panel.apply:Fire("OnClick")
    check("panel with the module: the next change keeps the object id", T.live[pid] == g1 and nearly(T.props[pid].rl, math.rad(-5), 1e-3)
        and nearly(T.props[pid].pt, math.rad(10), 1e-3) and lastCmd():find(" 10%.0 %-5%.0$"))
    panel.box.scale:SetText("1.50")
    serverClock = serverClock + 1
    panel.apply:Fire("OnClick")
    check("panel with the module: size as .build scale <id>, in place", lastCmd() == "scale " .. pid .. " 1.50" and T.live[pid] == g1
        and objects[g1].size == 1.5)
    gp = T.props[pid]
    serverClock = serverClock + 1
    local nCalls = #calls
    E.GizmoCommit(g1, 0, 0, 1, 0, gp.x, gp.y, gp.z + 1)
    check("gizmo with the module: moved in place, its tilt kept", T.live[pid] == g1 and nearly(objects[g1].z, gp.z)
        and nearly(T.props[pid].pt, math.rad(10), 1e-3) and lastCmd():find(" 10%.0 %-5%.0$"))
    local reselect = false
    for i = nCalls + 1, #calls do if calls[i]:find("^select ") then reselect = true end end
    check("gizmo with the module: the handles aren't re-put on the same object", not reselect)
    B.ShowProps(false)
    Sandbox, LeylineEdit = nil, nil
end

-- 2026-10-30: redo, put away and the Storage tab, groups, the Den panel ------------------------------------------------
do
    local E = W.EditMode
    serverClock = serverClock + 5
    B.pick = B.catalog[1]
    B.Command("spawn " .. B.catalog[1].id)
    local pid = T.selected[7]
    E.Cmd("undo")
    check("edit mode Undo, then Redo (Ctrl+Y): the prop back", T.props[pid] == nil and (E.Cmd("redo") or true) and T.props[pid] ~= nil
        and sent[#sent][2] == "wubuild\tcmd\t1/1\tredo")
    check("the state counts undo and redo", B.state.undo and B.state.redo == "0")
    E.Cmd("store")
    check("Put away: into storage, and the Storage tab knows", T.props[pid] == nil and B.storage[B.catalog[1].id] == 1)
    local menu = B.Menu()
    B.menuTab = "storage"; B.ShowMenu(true); B.MenuRefresh()
    check("the Storage tab lists it with its count", menu.cells[1].item == B.catalog[1] and menu.cells[1]:GetText():find(" x1$"))
    serverClock = serverClock + 5
    menu.cells[1]:Fire("OnClick", "LeftButton")
    check("placing it from the Storage tab takes it out", (B.storage[B.catalog[1].id] or 0) == 0)
    B.MenuRefresh()
    check("and the tab is empty again", not menu.cells[1]:IsShown() and menu.empty:GetText():find("Nothing put away"))
    B.ShowMenu(false); B.menuTab = "all"
    E.Cmd("rm -rf")
    check("edit mode sends only its own commands", not sent[#sent][2]:find("rm"))

    -- the Den panel: the realm's info, the invite link to copy
    local nSent = #sent
    E.ShowDen(true)
    local den = E.DenPanel()
    check("/den opens the Den panel and asks for the info", den and den:IsShown() and SlashCmdList.LEYLINEDEN
        and sent[nSent + 1] and sent[nSent + 1][2] == "wuden\tinfo\t1/1\t")
    fireClient("OVMOD", "wuden\tinfo\t1/1\trole=owner;theme=stone;builders=Bea Cy;invite=1", "WHISPER", "Tester")
    check("info: role, builders, look", den.role:GetText():find("Your Den") and den.builders:GetText() == "Builders: Bea, Cy"
        and den.look:GetText() == "Room: stone" and den.ownerOnly[1].enabled ~= false)
    fireClient("OVMOD", "wuden\tinfo\t1/1\trole=visitor;theme=white;builders=-;invite=0", "WHISPER", "Someone")
    check("info from anyone else is ignored", den.role:GetText():find("Your Den"))
    fireClient("OVMOD", "wuden\tinfo\t1/1\trole=visitor;theme=white;builders=-;invite=0", "WHISPER", "Tester")
    check("a visitor: the owner's buttons are off", den.role:GetText():find("visiting") and den.ownerOnly[1].enabled == false
        and den.builders:GetText() == "Builders: only the owner")
    local link = "https://relay.example.app/join/abcdefghij234567#ABCDEFGH23456789XYZQ"
    fireClient("OVMOD", "wuden\tinvite\t1/1\t" .. link, "WHISPER", "Tester")
    check("Invite a friend: the link in a box to copy", den.link:GetText() == link and E.note:find("Ctrl%+C"))
    den.link:SetText("typed over"); den.link:Fire("OnTextChanged")
    check("the link box can't be typed over", den.link:GetText() == link)
    fireClient("OVMOD", "wuden\tinvite\t1/1\tjavascript:alert(1)", "WHISPER", "Tester")
    check("only a join link is shown", den.link:GetText() == link)
    den.name:SetText("Bea")
    nSent = #sent
    for _, f in ipairs(created) do if f.parent == den and f.text == "Can build" then f:Fire("OnClick") end end
    check("Can build sends .den allow <name> build", sent[nSent + 1] and sent[nSent + 1][2] == "wuden\tcmd\t1/1\tallow Bea build")
    den.layout:SetText("my room!")
    nSent = #sent
    for _, f in ipairs(created) do if f.parent == den and f.text == "Save" then f:Fire("OnClick") end end
    check("a bad layout name never leaves the panel", #sent == nSent)
    den.layout:SetText("cosy")
    for _, f in ipairs(created) do if f.parent == den and f.text == "Load, replacing" then f:Fire("OnClick") end end
    check("Load, replacing", sent[#sent][2] == "wuden\tcmd\t1/1\tload cosy replace")
    E.ShowDen(false)
    check("closes", not den:IsShown())
end

-- the client ignores messages that aren't the realm's answer to us
fireClient("OVMOD", "wubuild\tstate\t1/1\tsel=1,2,Spoof;mine=9/9;area=x;code=-", "WHISPER", "Someone")
check("ignores other senders", not win.sel:GetText():find("Spoof"))
-- a catalog in two parts
fireClient("OVMOD", "wubuild\tcatalog\t1/2\t2413,chair,seating,Wooden", "WHISPER", "Tester")
fireClient("OVMOD", "wubuild\tcatalog\t2/2\t Chair;181075,table,tables,Table", "WHISPER", "Tester")
check("multi-part catalog reassembled", #B.catalog == 2 and B.catalog[1].name == "Wooden Chair")

-- no realm script: says so
onServerAddon = nil
win.reload:Fire("OnClick")
check("asking...", win.status:GetText():find("^Asking"))
clock = clock + 10
win:Fire("OnUpdate", 0.1)
check("no answer: the Builder isn't on this realm", win.status:GetText():find("isn't on this realm"))

win:Hide()
SlashCmdList.WUBUILDER("")
check("/builder toggles it", win:IsShown())

-- nothing the window shows names the game or its maker
local bad
for _, f in ipairs(created) do
    local t = (f.kind == "FontString" or f.kind == "Button") and f.text or nil
    if t and (t:lower():find("warcraft") or t:lower():find("%f[%w]wow%f[%W]") or t:lower():find("lich king")
        or t:lower():find("blizzard") or t:find("Open ?Vanilla") or t:find("OpenWoW")) then bad = t end
end
check("no game-brand or old project names on screen", bad == nil)
if bad then print("  shown: " .. bad) end

os.time = realTime
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
