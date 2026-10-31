-- ov_den.lua: a Den, your own room to build in (mod-ale, 3.3.5a). Only on a realm with OV_DEN=1
-- (realm/profiles/den.env: the host kit's "den" profile, a private realm on the owner's PC; docs/DEN.md).
--
-- Every character starts alone in a plain white room and builds it into their Den: F7 (edit mode) or /builder
-- place props from the realm's catalog (ov_build.lua does all the building and checks every change). This script
-- is the room around it:
--   * the room: a floor, four walls with a doorway to the yard and four lights, made of catalog props owned by
--     the Den itself (free of every budget; only the owner changes them). Built the first time someone is there.
--     The spot: ov_build.lua's DEN (the sealed island in the far north-east corner of Kalimdor, map 1).
--   * the edge: anyone outside the Den (walked or fell out, another map, a teleport) is put back in the room within
--     a few seconds. GMs with .gm on are free to leave. New characters start in the room, with their hearth there.
--   * who does what: the owner (the realm's GM: the host kit gives the host's account GM level 3) always builds
--     and changes the room; builders are the friends the owner allows (.den allow <name> build); everyone else
--     with the invite link visits: looks around, nothing more.
--
--   .den                          what this is, and your role here
--   .den home                     back to the middle of the room
--   .den invite                   (owner) the realm's invite link to give a friend; the Den bar shows it to copy
--   .den builders                 who may build here
--   .den allow <name> build|view  (owner) lets a friend build, or back to looking only (they must be online to add)
--   .den room [white|stone|wood]  (owner) the room's look; ".den room rebuild" puts it up again, "clear" takes it down
--   .den budget                   the decor budgets: inside the room and out in the yard
--   .den save|load <name> [replace] | .den layouts     the whole Den as a layout (.build layout)
--
-- The Den bar (WrathUnleashedUI/EditMode.lua) talks to this over the OVMOD channel (ov_modapi.lua), mod "wuden":
--   client -> server   cmd      <the text after .den>
--   server -> client   info     role=<owner|builder|visitor>;theme=<look>;builders=<a b c>;invite=<0|1>
--                      invite   <the invite link>          (the owner only)
--
-- Files: <kit>/realm-files/lua_scripts/den-invite.dat (the host kit's setup.py, den profile only), data only:
--   return { invite = "https://.../join/<realm id>#<invite secret>" }       read, never run (OV_DEN_INVITE_FILE)
-- Table: mod_den_settings (k, v): the room's look and its floor height.
-- mod-ale used: RegisterPlayerEvent 3 ON_LOGIN, 28 ON_MAP_CHANGE, 30 ON_FIRST_LOGIN, 42 ON_COMMAND; CreateLuaEvent;
-- Player:Teleport / IsGM / GetGMRank / SetBindPoint / RegisterEvent / SendBroadcastMessage; Map:GetHeight;
-- GetPlayersInWorld, GetPlayerByName, CharDBQuery / CharDBExecute.

if os.getenv("OV_DEN") ~= "1" then return end

local TAG = "|cffc8a2ff[Den]|r "
local MOD = "wuden"
local FILE = os.getenv("OV_DEN_INVITE_FILE") or "/azerothcore/lua_scripts/den-invite.dat"
local CHECK_MS = 2000          -- the edge check
local BACK_COOLDOWN = 3        -- seconds between two "back in the room" for one player
local AREA_ID = 876            -- AreaTable.dbc: the island's own area (the hearth's area)
local ADDON_WAIT = 20          -- seconds after a login without a word from the addon: say how to get it

local OVMod
do
    local ok, m = pcall(function() return require("ov_modapi") end)
    if ok and type(m) == "table" then OVMod = m end
    if not OVMod and type(rawget(_G, "OVMod")) == "table" then OVMod = rawget(_G, "OVMod") end
end

local function say(player, text) player:SendBroadcastMessage(TAG .. text) end

local function try(obj, method, ...)
    if not obj then return nil end
    local ok, fn = pcall(function() return obj[method] end)
    if not ok or type(fn) ~= "function" then return nil end
    local ok2, a, b = pcall(fn, obj, ...)
    if ok2 then return a, b end
    return nil
end

local function query(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
    return nil
end
local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end

-- ov_build.lua loads first (file order) or later: OVBuild is looked up at each use.
local function B() local b = rawget(_G, "OVBuild"); return (type(b) == "table" and b.DEN) and b or nil end
local function den() local b = B(); return b and b.DEN end

local function isOwner(player) return (tonumber(try(player, "GetGMRank")) or 0) > 0 end
local function free(player) return try(player, "IsGM") == true end   -- a GM with .gm on goes where they like

local function role(player)
    if isOwner(player) then return "owner" end
    local b = B()
    local l = (player:GetName() or ""):lower()
    for _, n in ipairs(b and b.Builders() or {}) do if n:lower() == l then return "builder" end end
    return "visitor"
end

------------------------------------------------------------------------------------------------
-- settings: the look and the floor height
------------------------------------------------------------------------------------------------
exec("CREATE TABLE IF NOT EXISTS mod_den_settings (k VARCHAR(16) NOT NULL PRIMARY KEY, v VARCHAR(64) NOT NULL)")
local settings = {}
do
    local q = query("SELECT k, v FROM mod_den_settings")
    if q then repeat settings[q:GetString(0)] = q:GetString(1) until not q:NextRow() end
end
local function setSetting(k, v)
    settings[k] = v
    exec(string.format("REPLACE INTO mod_den_settings (k, v) VALUES ('%s', '%s')", k, tostring(v):gsub("[^%w%.%-]", "")))
end

------------------------------------------------------------------------------------------------
-- the room
------------------------------------------------------------------------------------------------
-- Looks: catalog entries only (ov_build.lua's allowlist, checked against the world database). tile: yards between
-- two floor or wall pieces, rows: how many pieces high the walls are. How each looks in game is "to verify";
-- OV_DEN_TILE sets the spacing for all of them.
local THEMES = {
    white = { name = "white", floor = 188142, wall = 188142, light = 190664, tile = 4, rows = 2 },   -- big light blocks
    stone = { name = "stone", floor = 190024, wall = 19444, light = 180043, tile = 4, rows = 1 },    -- platform, rock wall
    wood  = { name = "wood", floor = 190615, wall = 211062, light = 179977, tile = 4, rows = 1 },    -- platform, wooden fence
}

local function themeOf(name) return THEMES[tostring(name or ""):lower()] end
local function currentTheme() return themeOf(settings.theme) or themeOf(os.getenv("OV_DEN_THEME")) or THEMES.white end

local function floorZ()
    local d = den()
    return tonumber(settings.floor or "") or (d and d.z) or 0
end

-- The room's pieces, in world coordinates: { entry, x, y, z, o }. The south wall keeps a doorway out to the yard.
local function plan(t, fz)
    local d = den()
    local tile = tonumber(os.getenv("OV_DEN_TILE") or "") or t.tile
    if tile < 1 then tile = 1 end
    if tile > 10 then tile = 10 end
    local half = d.half
    local offs = {}
    local n = math.max(1, math.floor(half * 2 / tile + 0.5))
    for i = 1, n do offs[i] = -half + tile * (i - 0.5) end
    local out = {}
    local function add(entry, x, y, z, o, s) out[#out + 1] = { entry = entry, x = x, y = y, z = z, o = o or 0, s = s } end
    -- With the models' bounds (the server's own GameObjectDisplayInfo, OVBuild.ModelBox) every block is sized to
    -- exactly one tile, the floor's tops level with the ground: one seamless, flat surface. Without them, the
    -- blocks stand at their own size on the ground (the spacing is "to verify" in game).
    local b = B()
    local function fit(entry)
        if not (b and b.ModelBox) then return nil end
        local w, dp, lo, hi = b.ModelBox(entry)
        if not w or w <= 0.05 or hi - lo <= 0.01 then return nil end
        local s = math.max(0.1, math.min(5, tile / math.max(w, dp)))
        return s, lo * s, hi * s
    end
    local fs, _, ftop = fit(t.floor)
    for _, ox in ipairs(offs) do
        for _, oy in ipairs(offs) do add(t.floor, d.x + ox, d.y + oy, fs and (fz - ftop) or fz, 0, fs) end
    end
    local ws, wlo, whi = fit(t.wall)
    for r = 0, t.rows - 1 do
        local z = ws and (fz - wlo + (whi - wlo) * r) or (fz + tile * (r + 0.5))
        for _, o in ipairs(offs) do
            add(t.wall, d.x + o, d.y + half, z, 0, ws)                         -- north
            if math.abs(o) > tile then add(t.wall, d.x + o, d.y - half, z, 0, ws) end   -- south, the doorway in its middle
            add(t.wall, d.x + half, d.y + o, z, math.pi / 2, ws)                -- east
            add(t.wall, d.x - half, d.y + o, z, math.pi / 2, ws)                -- west
        end
    end
    local c = half - 2
    for _, s in ipairs({ { 1, 1 }, { 1, -1 }, { -1, 1 }, { -1, -1 } }) do add(t.light, d.x + s[1] * c, d.y + s[2] * c, fz) end
    return out
end

-- Puts the room up when it isn't there (or force: again, in look t). player: who is there now (their grid).
local function buildRoom(player, t, force)
    local b = B()
    if not b then return 0 end
    if b.RoomCount() > 0 and not force then return 0 end
    if b.RoomCount() > 0 then b.ClearRoom(player) end
    t = t or currentTheme()
    local d = den()
    -- the floor height: measured once where the room stands (the ground there), then kept
    if not settings.floor then
        local map = try(player, "GetMap")
        local h = map and tonumber(try(map, "GetHeight", d.x, d.y))
        local fz = (h and math.abs(h - d.z) <= 30) and h or d.z
        setSetting("floor", string.format("%.2f", fz))
    end
    b.SetFloor(floorZ())
    setSetting("theme", t.name)
    if settings.cleared then settings.cleared = nil; exec("DELETE FROM mod_den_settings WHERE k = 'cleared'") end
    return b.PlaceRoom(player, plan(t, floorZ()))
end

------------------------------------------------------------------------------------------------
-- the edge
------------------------------------------------------------------------------------------------
local lastBack = {}

local function inside(player)
    local d = den()
    if not d then return true end
    if player:GetMapId() ~= d.map then return false end
    local dx, dy = player:GetX() - d.x, player:GetY() - d.y
    local z, fz = player:GetZ(), floorZ()
    return math.sqrt(dx * dx + dy * dy) <= d.r and z >= fz - 12 and z <= fz + 50
end

local function toRoom(player, quiet)
    local d = den()
    if not d then return end
    try(player, "Teleport", d.map, d.x, d.y, floorZ() + 1, math.pi / 2)
    if not quiet then say(player, "That's the edge of the Den: back in the room. (|cffffff00.den|r says what's here.)") end
end

-- The building tools (edit mode, the Builder, the Den panel) are the Leyline UI addon (WrathUnleashedUI): the
-- browser client has it built in; a player's own game gets it from the launcher (Addons). The addon asks for
-- the Den's info when it loads (EditMode.lua, PLAYER_ENTERING_WORLD); whoever stays silent hears how to get it.
local loginAt, heard, hinted = {}, {}, {}
local function addonHint(player)
    local g = player:GetGUIDLow()
    if heard[g] or hinted[g] or not loginAt[g] or os.time() - loginAt[g] < ADDON_WAIT then return end
    hinted[g] = true
    say(player, "Building here works best with the Leyline UI addon: edit mode, the Builder window and the Den panel. "
        .. "Get it in the Leyline launcher (Addons, then Leyline UI) and restart the game.")
    say(player, "Until then, everything works as commands: |cffffff00.den|r and |cffffff00.build help|r.")
end

local function checkOne(player)
    if not player then return end
    addonHint(player)
    if inside(player) then
        -- the room goes up the first time anyone stands in the Den (its grid is loaded then)
        local b = B()
        if b and b.RoomCount() == 0 and not settings.cleared then buildRoom(player) end
        return
    end
    if free(player) then return end
    local g, now = player:GetGUIDLow(), os.time()
    if lastBack[g] and now - lastBack[g] < BACK_COOLDOWN then return end
    lastBack[g] = now
    toRoom(player)
end

local function checkAll()
    if not GetPlayersInWorld then return end
    local ok, list = pcall(GetPlayersInWorld)
    if not ok or type(list) ~= "table" then return end
    for _, pl in ipairs(list) do pcall(checkOne, pl) end
end

------------------------------------------------------------------------------------------------
-- invite, builders, info
------------------------------------------------------------------------------------------------
-- The link from den-invite.dat, read as data (never run): an https join link, nothing else.
local function inviteLink()
    local f = io and io.open and io.open(FILE, "r")
    if not f then return nil end
    local text = f:read("*a") or ""
    f:close()
    local link = text:match('invite%s*=%s*"(https://[%w%.%-]+/join/[a-z2-7]+#[A-Z2-9]+)"')
    if link and #link < 200 then return link end
    return nil
end

local function sendInfo(player)
    if not OVMod then return end
    local b = B()
    local names = b and b.Builders() or {}
    pcall(OVMod.Send, player, MOD, "info", string.format("role=%s;theme=%s;builders=%s;invite=%d", role(player),
        currentTheme().name, #names > 0 and table.concat(names, " ") or "-", (isOwner(player) and inviteLink()) and 1 or 0))
end

local function inviteCommand(player)
    if not isOwner(player) then return say(player, "Only the Den's owner hands out the invite link: ask them for it.") end
    local link = inviteLink()
    if not link then
        return say(player, "Your invite link is on the launcher's Host page (Copy invite link), and in your host kit "
            .. "folder: state\\invite.txt. Anyone with it can join this Den.")
    end
    say(player, "Give a friend this link: |cffffff00" .. link .. "|r")
    say(player, "Anyone with it can join, so share it only with friends. A new link (the old one stops working): "
        .. "the launcher's Host page, New invite link.")
    if OVMod then pcall(OVMod.Send, player, MOD, "invite", link) end
end

local function buildersCommand(player)
    local b = B()
    local names = b and b.Builders() or {}
    if #names == 0 then
        say(player, "Builders: only the owner so far." .. (isOwner(player) and " |cffffff00.den allow <name> build|r lets a friend build." or ""))
    else
        say(player, "Builders (besides the owner): " .. table.concat(names, ", ") .. ".")
    end
end

local function allowCommand(player, words)
    if not isOwner(player) then return say(player, "Only the Den's owner decides who builds.") end
    local name, what = words[2], (words[3] or "build"):lower()
    if not name or not (what == "build" or what == "view") then
        return say(player, "Usage: |cffffff00.den allow <name> build|r (they may build) or |cffffff00.den allow <name> view|r (look only)")
    end
    local ok, text = B().SetBuilder(player, name, what == "build")
    say(player, text or "")
    if ok then sendInfo(player) end
end

local function roomCommand(player, words)
    if not isOwner(player) then return say(player, "Only the Den's owner changes the room.") end
    local w = (words[2] or ""):lower()
    if w == "" then
        return say(player, string.format("The room is %s (%d pieces). |cffffff00.den room white|stone|wood|r changes its look, "
            .. "|cffffff00rebuild|r puts it up again, |cffffff00clear|r takes it down. Your decor stays either way.",
            currentTheme().name, B().RoomCount()))
    end
    if w == "clear" then
        local n = B().ClearRoom(player)
        setSetting("cleared", "1")   -- stays down until rebuilt
        return say(player, string.format("The room is down (%d pieces); |cffffff00.den room rebuild|r puts it back.", n))
    end
    local t = (w == "rebuild") and currentTheme() or themeOf(w)
    if not t then return say(player, "Looks: white, stone, wood.") end
    local n = buildRoom(player, t, true)
    say(player, string.format("The room is up again, %s (%d pieces).", t.name, n))
    sendInfo(player)
end

local function budgetCommand(player)
    local i, ic, o, oc = B().DenUsage()
    say(player, string.format("Decor budget: the room %d of %d points, the yard %d of %d. A prop's points are in the "
        .. "spawn menu; putting one away (|cffffff00.build store|r) frees them.", i, ic, o, oc))
end

local function helpCommand(player)
    local r = role(player)
    say(player, "This is a Den: a room to build in, private to its owner and the friends they invite.")
    if r == "visitor" then
        say(player, "You're visiting: look around as you like. The owner can make you a builder.")
    else
        say(player, "You build here (" .. r .. "): F7 is edit mode (hold Q for props, G to carry, Ctrl+Z undo, Ctrl+Y redo).")
        say(player, "  |cffffff00.den budget|r  |cffffff00.den save <name>|r  |cffffff00.den load <name>|r  |cffffff00.den layouts|r  |cffffff00.den builders|r")
    end
    if r == "owner" then
        say(player, "  Owner: |cffffff00.den invite|r  |cffffff00.den allow <name> build|view|r  |cffffff00.den room white|stone|wood|rebuild|r")
    end
    say(player, "  |cffffff00.den home|r takes you back to the middle of the room.")
end

local function run(player, text)
    local words = {}
    for w in tostring(text or ""):gmatch("%S+") do if #words < 6 then words[#words + 1] = w:sub(1, 24) end end
    local sub = (words[1] or "help"):lower()
    if not B() then return say(player, "The Builder isn't on this realm, so the Den can't work.") end
    if sub == "home" then toRoom(player, true); return say(player, "Back in the room.")
    elseif sub == "invite" then return inviteCommand(player)
    elseif sub == "builders" then return buildersCommand(player)
    elseif sub == "allow" then return allowCommand(player, words)
    elseif sub == "room" then return roomCommand(player, words)
    elseif sub == "budget" then return budgetCommand(player)
    elseif sub == "save" or sub == "load" then
        local name = (words[2] or ""):gsub("[^%w_%-]", "")
        if name == "" then return say(player, "Usage: |cffffff00.den " .. sub .. " <name>|r") end
        return B().Run(player, "layout " .. sub .. " " .. name .. ((sub == "load" and (words[3] or ""):lower() == "replace") and " replace" or ""))
    elseif sub == "layouts" then return B().Run(player, "layout list")
    end
    helpCommand(player)
end

------------------------------------------------------------------------------------------------
-- events
------------------------------------------------------------------------------------------------
local function onCommand(event, player, command)
    if not player then return end
    local text = (command or ""):gsub("^[%.!]", "")
    local verb, rest = text:match("^(%S+)%s*(.*)$")
    if (verb or ""):lower() ~= "den" then return end
    run(player, rest)
    sendInfo(player)
    return false
end

local function arrive(player)
    if not player or not den() then return end
    if inside(player) and not settings.cleared then buildRoom(player) end
    local b = B()
    if b then b.SetFloor(floorZ()) end
    sendInfo(player)
end

local function onLogin(event, player)
    if not player then return end
    local g = player:GetGUIDLow()
    loginAt[g], heard[g], hinted[g] = os.time(), nil, nil
    if not free(player) and not inside(player) then toRoom(player, true) end
    arrive(player)
end

local function onMap(event, player) arrive(player) end

-- A new character: into the room (a moment after the login, once they are in the world), the hearth set there.
local function onFirstLogin(event, player)
    if not player then return end
    local d = den()
    if not d then return end
    try(player, "SetBindPoint", d.x, d.y, floorZ() + 1, d.map, AREA_ID)
    local function go(_, _, _, pl)
        pl = pl or player
        toRoom(pl, true)
        say(pl, "Welcome to the Den: a plain room for now. Press F7 to start building (or type .den).")
    end
    if not try(player, "RegisterEvent", go, 1500, 1) then go() end
end

RegisterPlayerEvent(3, onLogin)        -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(28, onMap)         -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterPlayerEvent(30, onFirstLogin)  -- PLAYER_EVENT_ON_FIRST_LOGIN
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND
if CreateLuaEvent then CreateLuaEvent(checkAll, CHECK_MS, 0) end

if OVMod then
    OVMod.On(MOD, "cmd", function(player, data)
        heard[player:GetGUIDLow()] = true
        if #(data or "") > 80 then return end
        run(player, data)
        sendInfo(player)
    end)
    OVMod.On(MOD, "info", function(player) heard[player:GetGUIDLow()] = true; sendInfo(player) end)
end

-- after a restart (or a Lua reload): the Builder knows the floor at once
if B() and settings.floor then B().SetFloor(floorZ()) end

-- for stream/tests/test_ov_den.lua (read only)
OV_DEN_TEST = { THEMES = THEMES, plan = plan, buildRoom = buildRoom, inside = inside, checkAll = checkAll,
    inviteLink = inviteLink, settings = settings, run = run, role = role, heard = heard, ADDON_WAIT = ADDON_WAIT }
