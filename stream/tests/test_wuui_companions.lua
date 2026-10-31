-- lua5.1 stream/tests/test_wuui_companions.lua [addon dir] [ov_companions.lua] [ov_modapi.lua]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order, opens the Bots window (/comp) and runs real
-- round trips through ov_companions.lua and ov_modapi.lua (fake mod-ale, fake mod-playerbots): the roster after
-- a party fill, live health bars, the orders (stay, attack, passive, assist, crowd control, formation, prepare),
-- the per-bot menu (spec, role), dismiss, the minimap button, the chat filters (bot achievements, whispers after
-- an order), answers in the window and not the chat, and no game-brand names on screen.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local server = arg[2] or "realm/custom/lua_scripts/ov_companions.lua"
local modapi = arg[3] or server:gsub("ov_companions%.lua$", "ov_modapi.lua")

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_builder.lua)
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
function Frame:GetName() return self.name end
function Frame:SetChecked(v) self.checked = v end
function Frame:GetChecked() return self.checked end
function Frame:SetValue(v) self.value = v end
function Frame:SetTexCoord(...) self.coords = { ... } end
function Frame:SetTextColor(r, g, b) self.color = { r, g, b } end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent) local f = new(kind, name, parent); frames[#frames + 1] = f; return f end

UIParent = new("Frame", "UIParent"); UIParent.top = true
Minimap = new("Frame", "Minimap"); Minimap.top = true
GameMenuFrame = new("Frame", "GameMenuFrame"); GameMenuFrame.top = true; GameMenuFrame.h = 300
function Frame:GetHeight() return self.h or 0 end
function Frame:SetHeight(h) self.h = h end
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
local chatLines = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) chatLines[#chatLines + 1] = m end }
local filters = {}
function ChatFrame_AddMessageEventFilter(event, fn) filters[event] = fn end
RAID_CLASS_COLORS = { MAGE = { r = 0.41, g = 0.8, b = 0.94 }, WARRIOR = { r = 0.78, g = 0.61, b = 0.43 },
    DRUID = { r = 1, g = 0.49, b = 0.04 }, PRIEST = { r = 1, g = 1, b = 1 } }
PowerBarColor = { MANA = { r = 0, g = 0, b = 1 }, RAGE = { r = 1, g = 0, b = 0 } }
function GetScreenHeight() return 981 end
function InCombatLockdown() return false end
function SetBinding() return 1 end
function SetBindingClick() return 1 end
function SaveBindings() end
function SetCVar() end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end
local hasTarget = false
function UnitExists(u) return u == "target" and hasTarget end
function GetNumRaidMembers() return 0 end
local partyUnits = {}   -- party1.. -> bot
function UnitName(u)
    if u == "player" then return "Tester" end
    local b = partyUnits[u]
    return b and b.name or nil
end
function UnitHealth(u) local b = partyUnits[u]; return b and b.hp or 0 end
function UnitHealthMax(u) return partyUnits[u] and 1000 or 0 end
function UnitPower(u) local b = partyUnits[u]; return b and b.mp or 0 end
function UnitPowerMax(u) return partyUnits[u] and 500 or 0 end
function UnitPowerType() return 0, "MANA" end
function UnitIsDeadOrGhost(u) local b = partyUnits[u]; return b and b.dead or false end

-- ---------------------------------------------------------------- the realm (ov_companions.lua + ov_modapi.lua, fake mod-ale)
local realGetenv, realTime = os.getenv, os.time
local serverClock = 1000000
os.time = function() return serverClock end
os.getenv = function() return nil end
local onServerAddon
function RegisterServerEvent(id, fn) if id == 30 then onServerAddon = fn end end
local playerEvents = {}
function RegisterPlayerEvent(id, fn) playerEvents[id] = fn end
function CharDBExecute() end
function CharDBQuery() return nil end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end

local serverChat = {}
local function unit(o)
    local u = { whispers = {}, queue = {}, cmds = {}, level = 80, combat = false }
    for k, v in pairs(o) do u[k] = v end
    function u:GetGUIDLow() return self.guid end
    function u:GetGUID() return self.guid end
    function u:GetName() return self.name end
    function u:GetLevel() return self.level end
    function u:GetClass() return self.class end
    function u:GetAccountId() return self.account end
    function u:GetAccountName() return self.accName end
    function u:IsInCombat() return self.combat end
    function u:IsDead() return self.dead or false end
    function u:InBattleground() return false end
    function u:InArena() return false end
    function u:GetMap() return { IsDungeon = function() return false end, IsRaid = function() return false end } end
    function u:GetMapId() return 0 end
    function u:GetInstanceId() return 0 end
    function u:GetX() return 0 end
    function u:GetY() return 0 end
    function u:GetZ() return 0 end
    function u:GetO() return 0 end
    function u:GetDistance() return 5 end
    function u:GetGroup() return self.group end
    function u:Teleport() end
    function u:GetSelection() return hasTarget and {} or nil end
    function u:IsPlayerbot() return self.bot == true end
    function u:IsAddclassBot() return self.bot == true end
    function u:IsTank(bySpec) return false end
    function u:IsHealer(bySpec) return false end
    function u:RunCommand(c) self.cmds[#self.cmds + 1] = c end
    function u:RegisterEvent(fn, delay, rep) self.queue[#self.queue + 1] = { fn = fn, delay = delay, rep = rep } end
    function u:SendBroadcastMessage(m) serverChat[#serverChat + 1] = m end
    function u:SendAddonMessage(prefix, msg) fireClient(prefix, msg, "WHISPER", "Tester") end
    function u:GetEquippedItemBySlot(slot) if self.bot then return { GetItemLevel = function() return 187 end } end end
    function u:GetBotAI()
        if not self.bot then return nil end
        local me = self
        return {
            HandleCommand = function(_, kind, text, from)
                from.whispers[#from.whispers + 1] = { to = me, text = text }
                if text == "leave" and me.group then
                    for i, m in ipairs(me.group.members) do if m == me then table.remove(me.group.members, i) end end
                    me.group = nil
                end
            end,
            ChangeStrategy = function(_, change, state) me.strategies = (me.strategies or "") .. state .. change .. ";" end,
            GetMaster = function() return me.master end,
        }
    end
    return u
end

local player = unit({ guid = 7, name = "Tester", class = 8, account = 1, accName = "TESTER" })
package.preload["ov_modapi"] = function() return dofile(modapi) end
dofile(server)
local T = assert(OV_COMPANIONS_TEST)
check("the realm script has the window channel", T.window == true and onServerAddon ~= nil)

local sent = {}
function SendAddonMessage(prefix, msg, channel, target)
    sent[#sent + 1] = { prefix, msg, channel, target }
    serverClock = serverClock + 1
    if target == UnitName("player") and onServerAddon then onServerAddon(30, player, 7, prefix, msg, player) end
end

-- what mod-playerbots does for each addclass: a bot joins the group
local CLS = { warrior = 1, paladin = 2, hunter = 3, rogue = 4, priest = 5, dk = 6, shaman = 7, mage = 8, warlock = 9, druid = 11 }
local nextBot, served = 100, {}
local function serve()
    local made = {}
    for i, c in ipairs(player.cmds) do
        local cls = c:match("^playerbots bot addclass (%a+)$")
        if cls and not served[i] then
            served[i] = true
            nextBot = nextBot + 1
            local b = unit({ guid = nextBot, name = "Bot" .. string.char(64 + nextBot - 100), class = CLS[cls], account = 900,
                accName = "RNDBOT" .. nextBot, bot = true, master = player, hp = 1000, mp = 500 })
            if not player.group then
                player.group = { members = { player } }
                local g = player.group
                function g:GetMembers() return self.members end
                function g:GetMembersCount() return #self.members end
                function g:IsLeader(guid) return guid == player.guid end
                function g:IsRaidGroup() return false end
                function g:IsLFGGroup() return false end
                function g:IsBGGroup() return false end
            end
            table.insert(player.group.members, b); b.group = player.group
            made[#made + 1] = b
        end
    end
    for i, b in ipairs(made) do partyUnits["party" .. i] = b end
    return made
end
local function runServer()
    while #player.queue > 0 do
        local e = table.remove(player.queue, 1)
        for k = 1, e.rep do e.fn(k, e.delay, e.rep - k, player) end
    end
end

-- ---------------------------------------------------------------- load the addon in .toc order
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
local at = {}
for i, f in ipairs(files) do at[f] = i end
check(".toc lists Companions.lua (before Leyline.lua, which stays last)", at["Companions.lua"] and at["Companions.lua"] < at["Leyline.lua"])
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
os.getenv = realGetenv
local W = assert(WrathUnleashedUI)
local C = assert(W.Companions, "W.Companions")
check("builds nothing until opened", C.Window() == nil and not _G.WrathUnleashedBotsMinimapButton)
check("/companions and /comp", SLASH_WUCOMPANIONS1 == "/companions" and SLASH_WUCOMPANIONS2 == "/comp" and SlashCmdList.WUCOMPANIONS)
check("chat filters for bot achievements and whispers", filters.CHAT_MSG_ACHIEVEMENT and filters.CHAT_MSG_GUILD_ACHIEVEMENT
    and filters.CHAT_MSG_WHISPER and filters.CHAT_MSG_WHISPER_INFORM)
check("the bot module's 'configured with N bots' login line is hidden; its credit line stays", filters.CHAT_MSG_SYSTEM
    and filters.CHAT_MSG_SYSTEM(nil, "CHAT_MSG_SYSTEM", "|cff00ff00Playerbots:|r The server is configured with 0 bots.") == true
    and filters.CHAT_MSG_SYSTEM(nil, "CHAT_MSG_SYSTEM", "|cff00ff00This server runs with |cff00ccffmod-playerbots|r |cffcccccchttps://github.com/mod-playerbots/mod-playerbots|r") == false
    and filters.CHAT_MSG_SYSTEM(nil, "CHAT_MSG_SYSTEM", "You have learned a new spell.") == false)

-- entering the world: a roster ask a moment later; the realm has bots, so the minimap button shows
C.listener:Fire("OnEvent", "PLAYER_ENTERING_WORLD")
check("no ask at once", #sent == 0)
clock = clock + 4
C.listener:Fire("OnUpdate", 0.1)
check("then the roster is asked over OVMOD, whispered to self", sent[1] and sent[1][1] == "OVMOD" and sent[1][2] == "wucomp\troster\t1/1\t"
    and sent[1][3] == "WHISPER" and sent[1][4] == "Tester")
check("the realm answered: bots on, none with you", C.state == "on" and #C.bots == 0 and C.cap == 4)
local mini = _G.WrathUnleashedBotsMinimapButton
check("minimap button shown once the realm has bots", mini and mini:IsShown() and mini.parent == Minimap)

-- open it
SlashCmdList.WUCOMPANIONS("")
local win = C.Window()
check("/comp opens the window; Esc closes it", win and win:IsShown() and UISpecialFrames[#UISpecialFrames] == "WrathUnleashedBotsFrame")
check("empty: says so and offers the group buttons", win.empty:GetText():find("No bots with you") and win.sub:GetText() == "0 of 4 bots in your party")
check("orders wait for bots", win.prepare.enabled == false and win.passive.enabled == false)

local function find(parent, text)
    for _, f in ipairs(created) do if f.parent == parent and f.text == text then return f end end
end
find(win, "Fill party"):Fire("OnClick")
check("Fill party: the realm recruits 4", #player.cmds == 4 and win.status:GetText():find("Recruiting 4 bots"))
check("the answer is in the window, not the chat", #serverChat == 0)
local bots = serve()
runServer()
check("they join: 4 rows, tank first", #C.bots == 4 and win.rows[1]:IsShown() and win.rows[4]:IsShown()
    and not win.rows[5]:IsShown() and C.bots[1].role == "tank")
check("every row says bot, its class colour, spec, item level and level", (function()
    for i = 1, 4 do
        local r = win.rows[i]
        if not (r.name:GetText():find("bot|r") and r.name:GetText():find("^|cff%x%x%x%x%x%x")
            and r.info:GetText():find("item level 187, level 80")) then return false end
    end
    return true end)())
check("role icons from the role sheet", win.rows[1].role.coords and win.rows[1].role.coords[1] == 0)
check("joined: shown in the window, not the chat", win.status:GetText():find("joins as a") and #serverChat == 0)
check("orders on now", win.prepare.enabled == true)

-- live bars
bots[1].hp = 500; bots[1].mp = 250
C.UpdateBars()
local r1
for _, r in ipairs(win.rows) do if r.bot and r.bot.name == bots[1].name then r1 = r end end
check("health and mana from the unit functions", r1.hp.value == 0.5 and r1.mp.value == 0.5)
bots[1].dead = true
C.UpdateBars()
check("dead shows Dead", r1.state:GetText() == "Dead")
bots[1].dead = false

-- bot chatter
local quietAch = filters.CHAT_MSG_ACHIEVEMENT(nil, "CHAT_MSG_ACHIEVEMENT", "%s has earned the achievement [Big Love Rocket]!", bots[2].name)
check("a bot's achievement line is hidden", quietAch == true)
check("someone else's achievement stays", filters.CHAT_MSG_ACHIEVEMENT(nil, "CHAT_MSG_ACHIEVEMENT", "x", "Friend") == false)
check("a bot's whisper right after it joined is hidden", filters.CHAT_MSG_WHISPER(nil, "CHAT_MSG_WHISPER", "Equipping gear", bots[2].name) == true)
clock = clock + 60
check("later, a bot's whisper shows (you asked it something)", filters.CHAT_MSG_WHISPER(nil, "CHAT_MSG_WHISPER", "Hi", bots[2].name) == false)
check("a friend's whisper always shows", filters.CHAT_MSG_WHISPER(nil, "CHAT_MSG_WHISPER", "Hi", "Friend") == false)

-- orders
local before = #player.whispers
find(win, "Stay"):Fire("OnClick")
check("Stay: every bot told stay through its AI", #player.whispers == before + 4 and player.whispers[#player.whispers].text == "stay")
check("rows say Staying", win.rows[2].state:GetText() == "Staying" and win.status:GetText() == "Staying here.")
check("whispers right after an order are hidden", filters.CHAT_MSG_WHISPER(nil, "CHAT_MSG_WHISPER", "Staying", bots[3].name) == true)
local sends = #sent
find(win, "Attack my target"):Fire("OnClick")
check("Attack without a target: asks for one, sends nothing", #sent == sends and win.status:GetText() == "Target something first.")
hasTarget = true
find(win, "Attack my target"):Fire("OnClick")
check("Attack my target", player.whispers[#player.whispers].text == "attack")
win.passive:Fire("OnClick")
check("Passive: silent strategy change; the button turns into Fight", bots[1].strategies:find("0%+passive") and win.passive:GetText() == "Fight")
win.passive:Fire("OnClick")
check("Fight: -passive", bots[1].strategies:find("0%-passive") and win.passive:GetText() == "Passive")
win.assist:Fire("OnClick")
check("Assist tank: on, shown green", C.assist and win.assist:GetText():find("^|cff7fff7f"))
win.cc:Fire("OnClick")
check("Crowd control: on", C.cc and win.cc:GetText():find("^|cff7fff7f"))
win.formation:Fire("OnClick")
local pick = _G.WrathUnleashedBotFormations
check("formation picker opens", pick and pick:IsShown())
find(pick, "Arrow"):Fire("OnClick")
check("Arrow: told, picker closed, button says so", player.whispers[#player.whispers].text == "formation arrow" and not pick:IsShown()
    and win.formation:GetText() == "Formation: Arrow")
win.prepare:Fire("OnClick")
check("Prepare for raid", win.status:GetText():find("Getting ready"))

-- the per-bot menu
local mage
for _, r in ipairs(win.rows) do if r.bot and r.bot.cls == 8 then mage = r end end
if not mage then for _, r in ipairs(win.rows) do if r.bot and r.bot.role == "dps" then mage = r end end end
mage:Fire("OnClick", "LeftButton")
local menu = _G.WrathUnleashedBotMenu
check("click a bot: its menu", menu and menu:IsShown() and menu.title:GetText():find(mage.bot.name))
local specBtn
for _, b in ipairs(menu.specBtns) do if b:IsShown() and b.enabled and b.spec then specBtn = b end end
check("specs from the realm's list, the current one not clickable", specBtn ~= nil)
local spec = specBtn.spec
specBtn:Fire("OnClick")
check("pick a spec: the realm teaches it, the row shows it", player.whispers[#player.whispers - 2].text == "talents spec " .. spec
    and not menu:IsShown() and mage.bot.spec == spec)
local roles = C.RolesFor(mage.bot.cls)
mage:Fire("OnClick", "LeftButton")
check("role buttons only for roles the class can take", (function()
    for _, rb in ipairs(menu.roleBtns) do
        local can = roles[rb.role] ~= nil and rb.role ~= mage.bot.role
        if (rb.enabled == true) ~= can then return false end
    end
    return true end)())
menu:Hide()

-- answers while the window is closed land in the chat frame, tagged
win:Hide()
C.Order("follow", "all")
check("closed window: the realm's answer goes to the chat frame", chatLines[#chatLines] == "|cff66ccff[Bots]|r Following you.")
win:Show()

-- the switch
win.quiet:SetChecked(false); win.quiet:Fire("OnClick")
check("Hide bot chatter off: achievements show", filters.CHAT_MSG_ACHIEVEMENT(nil, "CHAT_MSG_ACHIEVEMENT", "x", bots[2].name) == false
    and WrathUnleashedUIDB.botsChatter == true)
win.quiet:SetChecked(true); win.quiet:Fire("OnClick")
check("on again", filters.CHAT_MSG_ACHIEVEMENT(nil, "CHAT_MSG_ACHIEVEMENT", "x", bots[2].name) == true)

-- dismiss
find(win, "Dismiss all"):Fire("OnClick")
runServer()
check("Dismiss all: they leave, the window empties", #player.group.members == 1 and #C.bots == 0 and not win.rows[1]:IsShown()
    and win.sub:GetText() == "0 of 4 bots in your party")
check("nothing in the chat from any of it", #serverChat == 0)

-- a realm without bots: the window says so
player.IsPlayerbot = nil
C.Ask()
check("no bot module: 'coming soon'", C.state == "soon" and win.sub:GetText():find("coming soon"))

-- names on screen
local BANNED = { "world of warcraft", "warcraft", "lich king", "blizzard", "playerbot", "azerothcore", "companion" }
check("no brand names (or 'companion') on screen", (function()
    for _, f in ipairs(created) do
        local t = type(f.text) == "string" and f.text:lower() or ""
        for _, w in ipairs(BANNED) do if t:find(w, 1, true) then print("  on screen: " .. f.text); return false end end
        if t:find("%f[%a]wow%f[%A]") then return false end
    end
    return true end)())

os.time = realTime
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
