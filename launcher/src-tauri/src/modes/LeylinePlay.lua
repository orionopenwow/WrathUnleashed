-- LeylinePlay: written into your own game client by the Leyline launcher (launcher/src-tauri/src/modes.rs) when you
-- press PLAY on a game mode on its Modes page. Pending.lua, next to this file, names the mode:
--     LEYLINE_PENDING = { mode = "minigolf", nonce = "...", made = <seconds since 1970> }
-- After you log in, this asks the realm once to start that mode, on the realm's OVMOD channel (mod "wuplay", the same
-- as typing .playmode <mode>). The realm checks the mode (realm/custom/lua_scripts/ov_playmode.lua). A pick older
-- than 15 minutes, or one already asked for (LeylinePlayDB, your saved variables), is never asked again. It does
-- nothing else, and is harmless on a realm that has no modes. Remove the folder any time; PLAY writes it again.
local MAX_AGE = 900   -- seconds
local DELAY = 8       -- seconds after entering the world: after the realm's own login messages

local p = LEYLINE_PENDING
local wait, asked

local function valid(t)
    return type(t) == "table" and type(t.mode) == "string" and #t.mode <= 24 and t.mode:match("^[a-z][a-z0-9%-]*$") ~= nil
        and type(t.nonce) == "string" and #t.nonce <= 32 and t.nonce:match("^%w+$") ~= nil and type(t.made) == "number"
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_ENTERING_WORLD")
f:SetScript("OnEvent", function(self, event)
    if event ~= "PLAYER_ENTERING_WORLD" or asked or wait or not valid(p) then return end
    local age = time() - p.made
    if age < -60 or age > MAX_AGE then return end
    if type(LeylinePlayDB) == "table" and LeylinePlayDB.done == p.nonce then return end
    wait = DELAY
end)
f:SetScript("OnUpdate", function(self, elapsed)
    if not wait then return end
    wait = wait - (elapsed or 0)
    if wait > 0 then return end
    wait, asked = nil, true
    if type(LeylinePlayDB) ~= "table" then LeylinePlayDB = {} end
    LeylinePlayDB.done = p.nonce
    SendAddonMessage("OVMOD", "wuplay\tgo\t1/1\t" .. p.mode, "WHISPER", UnitName("player"))
end)
