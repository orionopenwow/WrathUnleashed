-- Leyline minigolf, the realm half (mod-ale / Eluna). The first mode on Leyline's play layer.
--
-- The course, the balls and the physics live only on the players' clients (browser client 20261025i+,
-- WrathUnleashedUI/Golf.lua); nothing is spawned in the world and nothing anyone else sees changes. This
-- script is the referee: it opens sessions, orders turns, relays each shot's input (an aim and a power, two
-- integers) to everyone in the session, takes the shooter's report of where the ball stopped, counts strokes
-- and keeps the scorecard. Every client simulates the shot with the same deterministic code, so all of them
-- see the same roll; each client also reports the roll's hash, and a mismatch is announced and logged.
--
-- OVMOD channel (ov_modapi.lua), mod "wugolf":
--   client -> server   courses                         list the courses
--                      start <course>                  open a session here (party members nearby are invited)
--                      join <id> | leave | go          join an invite, leave, tee off (the host)
--                      shot <angle> <power>            on your turn: tenths of a degree 0-3599, permille 0-1000
--                      rest <shot> <end> <x> <y> <z> <hash>     where the roll ended (every member reports)
--                      skip                            host: skip the player whose turn it is (idle 45 s+)
--                      top <course> | replay <id>      the course's best rounds; one round's inputs to watch
--                      live | watch <id>               rounds being played nearby; spectate one (no turns)
--                      publish <course text>           (in parts) publish a course from the editor: everyone may play it
--   server -> client   courses  key,title,holes,par,author;...
--                      invite   <id> <host> <title>
--                      lobby    <id> <host> <title> <name,name,...>
--                      session  <id> <x> <y> <z> <o> <title>      then course <text> (parts)
--                      course   <course text>
--                      hole     <n> <par> <name>
--                      turn     <name> <stroke> <x> <y> <z> <color> <phase>
--                      shot     <name> <x> <y> <z> <angle> <power> <phase> <stroke> <shot>
--                      score    <name>=<s1>,<s2>,...;...       strokes per hole so far
--                      top      <course>\t<id,name,strokes,verified,players;...>
--                      replay   <id> <name> <strokes>\n<inputs: per hole "angle,power,phase;..." joined by |>\n<course text>
--                      msg      <text>
--                      done     <name>=<total>;...  then  end
-- mod-ale events: 4 ON_LOGOUT, 28 ON_MAP_CHANGE, 42 ON_COMMAND (".golf ..." does the same as the window).
-- Published courses live in mod_golf_courses (characters database): five per character, re-publishing the same
-- title replaces it; ".golf unpublish <key>" (GM) takes one down. A course is only geometry and names, so the
-- only text players can put on screen (titles, hole names) is cut to letters, digits and simple punctuation.

local OVMod
do
    -- ALE loads scripts in name order, so ov_modapi.lua may not have run yet: require loads it once.
    local ok, m = pcall(function() return require("ov_modapi") end)
    OVMod = (ok and type(m) == "table" and m) or _G.OVMod
    if not OVMod then
        print("[ov_golf] ov_modapi.lua is missing: minigolf needs the OVMOD channel; not loaded")
        return
    end
end

local MOD = "wugolf"
local TAG = "|cff8fe36b[Minigolf]|r "
local TICK_HZ = 120
local MAX_PLAYERS = 8
local INVITE_RANGE = 40
local REST_WAIT = 30          -- seconds to wait for the shooter's rest report
local IDLE_SKIP = 45          -- seconds before the host may skip an idle player
local SHOT_GAP = 1            -- seconds between one player's shots, at least
local MAX_COORD = 80

-- Courses: key -> { title, text }. Meadow Nine is a copy of crates/benilla-mode/courses/meadow-nine.course
-- (the client's practice copy is in Golf.lua; stream/tests/test_ov_golf.lua checks all three match).
-- More courses: drop a file that returns { key = "...", text = [[...]] } list in lua_scripts as
-- ov_golf_courses.lua (Workshop courses arrive this way once the Workshop serves them).
local COURSES = {
    { key = "meadow", text = [==[
# Meadow Nine: Leyline's first-party minigolf course. Open format: see crates/benilla-mode/src/golf.rs.
# Every hole is played on the same spot, where the session started; the tee is at 0 0 0 facing +z.
course Meadow Nine
by WrathUnleashed

hole 2 First Putt
tee  0 0 0
cup  0 0 10
turf 0 -0.25 5     1.5 0.25 6.5
wall  1.6 0.15 5   0.1 0.4 6.6
wall -1.6 0.15 5   0.1 0.4 6.6
wall 0 0.15 11.6   1.7 0.4 0.1
wall 0 0.15 -1.6   1.7 0.4 0.1

hole 3 Dogleg Right
tee  0 0 0
cup  6.5 0 8
turf 0 -0.25 4     1.25 0.25 5.25
turf 4.5 -0.25 8   3.25 0.25 1.25
wall -1.35 0.15 4      0.1 0.4 5.35
wall  1.35 0.15 2.65   0.1 0.4 4.0
wall 0 0.15 -1.35      1.35 0.4 0.1
wall 3.375 0.15 9.35   4.75 0.4 0.1
wall 4.725 0.15 6.65   3.375 0.4 0.1
wall 8.1 0.15 8        0.1 0.4 1.35
bump 1.35 0 6.65       0.25 0.5

hole 2 Up the Ramp
tee  0 0 0
cup  0 1 12.8
turf 0 -0.25 3        1.4 0.25 4
turf 0 0.263 8.579    1.4 0.25 1.581  0 -18.4
turf 0 0.75 12        1.4 0.25 2
wall  1.5 0.6 6.5     0.1 0.85 7.6
wall -1.5 0.6 6.5     0.1 0.85 7.6
wall 0 0.15 -1.1      1.6 0.4 0.1
wall 0 1.15 14.1      1.6 0.4 0.1

hole 3 The Windmill
tee  0 0 0
cup  0 0 12
turf 0 -0.25 6     1.5 0.25 7.5
spin 0 0.3 6       1.35 0.3 0.12  90
bump 0 0 6         0.18 0.75
wall  1.6 0.15 6   0.1 0.4 7.6
wall -1.6 0.15 6   0.1 0.4 7.6
wall 0 0.15 13.6   1.7 0.4 0.1
wall 0 0.15 -1.6   1.7 0.4 0.1

hole 3 Sand Trap
tee  0 0 0
cup  1 0 12
turf 0 -0.25 2       2 0.25 3
sand 0 -0.25 6.5     1.2 0.25 1.5
turf -1.6 -0.25 6.5  0.4 0.25 1.5
turf  1.6 -0.25 6.5  0.4 0.25 1.5
turf 0 -0.25 11      2 0.25 3
wall  2.1 0.15 6.5   0.1 0.4 7.6
wall -2.1 0.15 6.5   0.1 0.4 7.6
wall 0 0.15 14.1     2.2 0.4 0.1
wall 0 0.15 -1.1     2.2 0.4 0.1

hole 3 Bumper Alley
tee  0 0 0
cup  0 0 14
turf 0 -0.25 7      1.5 0.25 8.5
bump -0.6 0 4       0.3 0.5
bump  0.6 0 6.5     0.3 0.5
bump  0 0 7.9       0.22 0.5
bump -0.6 0 9.3     0.3 0.5
bump  0.6 0 11.6    0.3 0.5
wall  1.6 0.15 7    0.1 0.4 8.6
wall -1.6 0.15 7    0.1 0.4 8.6
wall 0 0.15 15.6    1.7 0.4 0.1
wall 0 0.15 -1.6    1.7 0.4 0.1

hole 3 Ice Bridge
tee  0 0 0
cup  0 0 12.5
turf 0 -0.25 1       1.5 0.25 2.5
ice  0 -0.25 6.5     0.6 0.25 3
turf 0 -0.25 12      1.5 0.25 2.5
water 0 -0.4 6.5     1.5 3
wall  1.6 0.15 1     0.1 0.4 2.5
wall -1.6 0.15 1     0.1 0.4 2.5
wall  1.6 0.15 12    0.1 0.4 2.5
wall -1.6 0.15 12    0.1 0.4 2.5
wall 0 0.15 14.6     1.7 0.4 0.1
wall 0 0.15 -1.6     1.7 0.4 0.1

hole 3 Slider Gate
tee  0 0 0
cup  0 0 11.5
turf 0 -0.25 6        1.5 0.25 7.5
wall -1.0 0.15 6      0.5 0.4 0.12
wall  1.0 0.15 6      0.5 0.4 0.12
slide -0.6 0.2 6.4    0.4 0.25 0.12   1.2 0   3
wall  1.6 0.15 6      0.1 0.4 7.6
wall -1.6 0.15 6      0.1 0.4 7.6
wall 0 0.15 13.6      1.7 0.4 0.1
wall 0 0.15 -1.6      1.7 0.4 0.1

hole 4 Grand Finale
tee  0 0 0
cup  0.8 1.5 15
turf 0 -0.25 3        1.5 0.25 4.5
boost 0 0 3.5         0.6 0.6  0 9
turf 0 0.516 9.588    1.5 0.25 2.136  0 -20.6
turf 0 1.25 14        2 0.25 2.5
bump -0.8 1.5 14.2    0.3 0.5
wall  1.6 0.6 4.95    0.1 0.85 6.55
wall -1.6 0.6 4.95    0.1 0.85 6.55
wall  2.1 1.65 14.05  0.1 0.4 2.55
wall -2.1 1.65 14.05  0.1 0.4 2.55
wall  1.85 1.65 11.4  0.25 0.4 0.1
wall -1.85 1.65 11.4  0.25 0.4 0.1
wall 0 1.65 16.6      2.2 0.4 0.1
wall 0 0.15 -1.6      1.7 0.4 0.1
]==] },
}

do
    local ok, extra = pcall(require, "ov_golf_courses")
    if ok and type(extra) == "table" then
        for _, c in ipairs(extra) do
            if type(c) == "table" and type(c.key) == "string" and c.key:match("^[%w_]+$") and type(c.text) == "string"
                and #c.text <= 24 * 1024 then
                COURSES[#COURSES + 1] = { key = c.key, text = c.text }
            end
        end
    end
end

-- Reads the header lines the referee needs: title, and each hole's par, tee and cup (the rest is the
-- client's business). Returns nil and a reason for text the client would refuse too.
local function readCourse(text)
    local c = { title = "Untitled course", holes = {} }
    local n = 0
    for raw in (text .. "\n"):gmatch("([^\n]*)\n") do
        n = n + 1
        local line = raw:gsub("#.*$", ""):gsub("^%s+", ""):gsub("%s+$", "")
        local word, rest = line:match("^(%S+)%s*(.*)$")
        if word == "course" then c.title = rest:sub(1, 48)
        elseif word == "hole" then
            local par, name = rest:match("^(%d)%s*(.*)$")
            par = tonumber(par)
            if not par or par < 1 then return nil, "line " .. n .. ": hole needs a par" end
            c.holes[#c.holes + 1] = { par = par, name = (name ~= "" and name or ("Hole " .. (#c.holes + 1))):sub(1, 40) }
        elseif word == "tee" or word == "cup" then
            local h = c.holes[#c.holes]
            if not h then return nil, "line " .. n .. ": " .. word .. " before the first hole" end
            local x, y, z = rest:match("^(%S+)%s+(%S+)%s+(%S+)")
            x, y, z = tonumber(x), tonumber(y), tonumber(z)
            if not z then return nil, "line " .. n .. ": " .. word .. " needs x y z" end
            h[word] = { x = x, y = y, z = z }
        end
    end
    if #c.holes == 0 then return nil, "no holes" end
    if #c.holes > 18 then return nil, "more than 18 holes" end
    for i, h in ipairs(c.holes) do
        if not h.tee or not h.cup then return nil, "hole " .. i .. " needs a tee and a cup" end
    end
    return c
end

local byKey = {}
for _, entry in ipairs(COURSES) do
    local c, why = readCourse(entry.text)
    if c then entry.course = c; byKey[entry.key] = entry
    else print("[ov_golf] course " .. entry.key .. " skipped: " .. tostring(why)) end
end

-- ------------------------------------------------------------------------------------------- helpers

local function try(obj, method, ...)
    if not obj or not obj[method] then return nil end
    local ok, a, b, c, d = pcall(obj[method], obj, ...)
    if ok then return a, b, c, d end
end

local function say(player, text) try(player, "SendBroadcastMessage", TAG .. text) end
local function send(player, name, data) if player then OVMod.Send(player, MOD, name, data or "") end end

local sessions = {}     -- [id] = session
local bySeat = {}       -- [guidLow] = session id (playing or invited)
local nextId = 1

local function now() return os.time() end

local function members(s)
    local list = {}
    for _, m in ipairs(s.players) do
        local p = GetPlayerByGUID and GetPlayerByGUID(m.guid) or m.player
        if p then list[#list + 1] = { seat = m, player = p } end
    end
    return list
end

local byWatch = {}     -- [guidLow] = session id, for spectators

local function watchers(s)
    local list = {}
    for _, w in ipairs(s.watchers or {}) do
        local p = GetPlayerByGUID and GetPlayerByGUID(w.guid) or w.player
        if p then list[#list + 1] = p end
    end
    return list
end

local function broadcast(s, name, data)
    for _, e in ipairs(members(s)) do send(e.player, name, data) end
    for _, p in ipairs(watchers(s)) do send(p, name, data) end
end

local function note(s, text)
    for _, e in ipairs(members(s)) do say(e.player, text); send(e.player, "msg", text) end
    for _, p in ipairs(watchers(s)) do send(p, "msg", text) end
end

local function phase(s) return (now() - s.t0) * TICK_HZ end

local function capFor(par) return math.min(par + 4, 9) end

local function scoreText(s)
    local parts = {}
    for _, m in ipairs(s.players) do
        local strokes = {}
        for h = 1, #s.course.holes do strokes[#strokes + 1] = m.strokes[h] and tostring(m.strokes[h]) or "-" end
        parts[#parts + 1] = m.name .. "=" .. table.concat(strokes, ",")
    end
    return table.concat(parts, ";")
end

local function total(m)
    local t = 0
    for _, v in pairs(m.strokes) do t = t + v end
    return t
end

local function fmt(v) return string.format("%.3f", v) end

-- --------------------------------------------------------------------------------------- persistence

local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end
exec([[CREATE TABLE IF NOT EXISTS mod_golf_scores (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  guid INT UNSIGNED NOT NULL, name VARCHAR(12) NOT NULL, course VARCHAR(32) NOT NULL,
  strokes SMALLINT UNSIGNED NOT NULL, par SMALLINT UNSIGNED NOT NULL, players TINYINT UNSIGNED NOT NULL,
  verified TINYINT UNSIGNED NOT NULL, played_at INT UNSIGNED NOT NULL, KEY course_strokes (course, strokes))]])

exec([[CREATE TABLE IF NOT EXISTS mod_golf_courses (
  ckey VARCHAR(32) NOT NULL PRIMARY KEY, author_guid INT UNSIGNED NOT NULL, author VARCHAR(12) NOT NULL,
  title VARCHAR(48) NOT NULL, text MEDIUMTEXT NOT NULL, updated_at INT UNSIGNED NOT NULL, KEY author (author_guid))]])

exec([[CREATE TABLE IF NOT EXISTS mod_golf_runs (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, guid INT UNSIGNED NOT NULL, name VARCHAR(12) NOT NULL,
  course VARCHAR(32) NOT NULL, strokes SMALLINT UNSIGNED NOT NULL, players TINYINT UNSIGNED NOT NULL,
  verified TINYINT UNSIGNED NOT NULL, inputs MEDIUMTEXT NOT NULL, played_at INT UNSIGNED NOT NULL,
  KEY course_strokes (course, strokes))]])

local MAX_PUBLISHED = 5
local MAX_COURSE_TEXT = 14 * 1024

-- Only what the course format needs survives: no quotes, no escapes, no colour codes.
local function cleanText(text)
    text = tostring(text or ""):gsub("\r", ""):gsub("\t", " ")
    return (text:gsub("[^%w \n%.%-#_:,!&]", ""))
end

local function addCourse(key, text, author, guid)
    local c, why = readCourse(text)
    if not c then return nil, why end
    local entry = { key = key, text = text, course = c, author = author, guid = guid }
    for i, e in ipairs(COURSES) do
        if e.key == key then COURSES[i] = entry; byKey[key] = entry; return entry end
    end
    COURSES[#COURSES + 1] = entry
    byKey[key] = entry
    return entry
end

if CharDBQuery then
    local ok, q = pcall(CharDBQuery, "SELECT ckey, author, author_guid, text FROM mod_golf_courses")
    if ok and q then
        repeat
            addCourse(q:GetString(0), cleanText(q:GetString(3)), q:GetString(1), q:GetUInt32(2))
        until not q:NextRow()
    end
end

local function best(guid, course)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, string.format(
        "SELECT MIN(strokes) FROM mod_golf_scores WHERE guid = %d AND course = '%s'", guid, course))
    if ok and q then return q:GetUInt32(0) end
end

-- ------------------------------------------------------------------------------------------ the game

local endSession

local function current(s) return s.players[s.turn] end

local function playerOf(seat) return (GetPlayerByGUID and GetPlayerByGUID(seat.guid)) or seat.player end

local function sendTurn(s)
    local m = current(s)
    s.phase, s.turnAt, s.pending = "aim", now(), nil
    s.lastTurn = string.format("%s %d %s %s %s %d %d", m.name, (m.strokes[s.hole] or 0) + 1,
        fmt(m.ball.x), fmt(m.ball.y), fmt(m.ball.z), m.color, phase(s))
    broadcast(s, "turn", s.lastTurn)
end

local function startHole(s)
    local h = s.course.holes[s.hole]
    for _, m in ipairs(s.players) do
        m.ball = { x = h.tee.x, y = h.tee.y + 0.11, z = h.tee.z }
        m.done = false
    end
    s.turn = 1
    broadcast(s, "hole", string.format("%d %d %s", s.hole, h.par, h.name))
    broadcast(s, "score", scoreText(s))
    sendTurn(s)
end

local function nextTurn(s)
    -- The same player keeps putting until the ball drops or the cap; then the next one; then the next hole.
    local m = current(s)
    if not m.done then return sendTurn(s) end
    for i = s.turn + 1, #s.players do
        if not s.players[i].done and not s.players[i].gone then s.turn = i; return sendTurn(s) end
    end
    broadcast(s, "score", scoreText(s))
    if s.hole < #s.course.holes then
        s.hole = s.hole + 1
        return startHole(s)
    end
    -- Done: totals, personal bests, the record.
    local res = {}
    local verified = (#s.players >= 2 and not s.desync) and 1 or 0
    for _, p in ipairs(s.players) do
        local t = total(p)
        res[#res + 1] = p.name .. "=" .. t
        local pb = best(p.guid, s.key)
        exec(string.format("INSERT INTO mod_golf_scores (guid, name, course, strokes, par, players, verified, played_at) VALUES (%d, '%s', '%s', %d, %d, %d, %d, %d)",
            p.guid, p.name, s.key, t, s.par, #s.players, verified, now()))
        -- A round with a skipped turn, a lost report or a leaver can't be replayed shot for shot.
        if not p.irregular and not p.gone then
            local holes = {}
            for h = 1, #s.course.holes do holes[h] = table.concat((p.log or {})[h] or {}, ";") end
            exec(string.format("INSERT INTO mod_golf_runs (guid, name, course, strokes, players, verified, inputs, played_at) VALUES (%d, '%s', '%s', %d, %d, %d, '%s', %d)",
                p.guid, p.name, s.key, t, #s.players, verified, table.concat(holes, "|"), now()))
        end
        local pl = playerOf(p)
        if pl then
            local diff = t - s.par
            say(pl, string.format("%s: %d strokes (%s%d against par %d)%s", s.course.title, t, diff > 0 and "+" or "", diff, s.par,
                (pb and t < pb) and " - a personal best!" or ""))
        end
    end
    broadcast(s, "done", table.concat(res, ";"))
    endSession(s, nil)
end

local function finishShot(s, reportEnd, x, y, z)
    local m = current(s)
    local strokes = (m.strokes[s.hole] or 0) + 1
    local penalty = reportEnd == "out" or reportEnd == "water"
    if penalty then strokes = strokes + 1 else m.ball = { x = x, y = y, z = z } end
    m.strokes[s.hole] = strokes
    local par = s.course.holes[s.hole].par
    if reportEnd == "holed" then
        m.done = true
        local d = strokes - par
        local words = { [-3] = "an albatross", [-2] = "an eagle", [-1] = "a birdie", [0] = "par", [1] = "a bogey", [2] = "a double bogey" }
        local what = strokes == 1 and "a hole in one!" or (words[d] or (strokes .. " strokes"))
        note(s, m.name .. " holes out with " .. what)
    elseif strokes >= capFor(par) then
        m.done = true
        m.strokes[s.hole] = capFor(par)
        note(s, m.name .. " picks up at " .. capFor(par))
    elseif penalty then
        note(s, m.name .. (reportEnd == "water" and " splashes in: +1" or " goes off the course: +1"))
    end
    s.phase = "between"
    broadcast(s, "score", scoreText(s))
    nextTurn(s)
end

endSession = function(s, why)
    if sessions[s.id] ~= s then return end
    sessions[s.id] = nil
    for _, m in ipairs(s.players) do
        if bySeat[m.guid] == s.id then bySeat[m.guid] = nil end
        local p = playerOf(m)
        if p then
            send(p, "end", why or "")
            if why then say(p, why) end
        end
    end
    for guid, id in pairs(bySeat) do if id == s.id then bySeat[guid] = nil end end
    for _, p in ipairs(watchers(s)) do send(p, "end", why or "") end
    for guid, id in pairs(byWatch) do if id == s.id then byWatch[guid] = nil end end
end

local function seatOf(s, guid)
    for i, m in ipairs(s.players) do if m.guid == guid then return m, i end end
end

local function lobbyText(s)
    local names = {}
    for _, p in ipairs(s.players) do names[#names + 1] = p.name end
    return string.format("%d %s %s %s", s.id, s.players[1].name, (s.course.title:gsub(" ", "_")), table.concat(names, ","))
end

local function stopWatching(player)
    local guid = player:GetGUIDLow()
    local s = sessions[byWatch[guid] or -1]
    byWatch[guid] = nil
    if not s then return end
    for i, w in ipairs(s.watchers or {}) do if w.guid == guid then table.remove(s.watchers, i) break end end
end

local function leave(player, quiet)
    local guid = player:GetGUIDLow()
    if byWatch[guid] then return stopWatching(player) end
    local id = bySeat[guid]
    if not id then return end
    bySeat[guid] = nil
    local s = sessions[id]
    if not s then return end
    local m, i = seatOf(s, guid)
    if not m then return end
    if s.state == "lobby" then
        table.remove(s.players, i)
        if #s.players == 0 or i == 1 then return endSession(s, "The host left; the game is off.") end
        broadcast(s, "lobby", lobbyText(s))
        return
    end
    m.gone, m.done = true, true
    if not quiet then note(s, m.name .. " left the game.") end
    local left = 0
    for _, p in ipairs(s.players) do if not p.gone then left = left + 1 end end
    if left == 0 then return endSession(s, nil) end
    if s.turn == i and s.state == "play" then nextTurn(s) end
end

local function seat(player, color)
    return { guid = player:GetGUIDLow(), name = player:GetName(), player = player, strokes = {}, color = color,
        ball = { x = 0, y = 0.11, z = 0 } }
end

local function startCommand(player, key)
    key = (key or ""):lower()
    if key == "" then key = COURSES[1].key end
    local entry = byKey[key]
    if not entry then return say(player, "No course called '" .. key .. "'. Try: .golf courses") end
    if bySeat[player:GetGUIDLow()] then leave(player, true) end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    local map = try(player, "GetMap")
    if map and (try(map, "IsBattleground") or try(map, "IsArena")) then return say(player, "Not in a battleground or arena.") end
    local x, y, z, o = player:GetX(), player:GetY(), player:GetZ(), player:GetO()
    -- The tee goes a few steps ahead of the host, so the putting camera isn't inside anyone's body.
    x, y = x + math.cos(o) * 4.5, y + math.sin(o) * 4.5
    local s = { id = nextId, key = key, course = entry.course, text = entry.text, state = "lobby", t0 = now(),
        players = { seat(player, 0) }, checks = {}, watchers = {}, map = player:GetMapId(), x = x, y = y, z = z, o = o, hole = 1, turn = 1 }
    s.par = 0
    for _, h in ipairs(s.course.holes) do s.par = s.par + h.par end
    nextId = nextId + 1
    sessions[s.id] = s
    bySeat[player:GetGUIDLow()] = s.id
    -- Party members nearby get an invite.
    local invited = 0
    local group = try(player, "GetGroup")
    local list = group and try(group, "GetMembers") or {}
    for _, p in ipairs(list or {}) do
        if p ~= player and p:GetGUIDLow() ~= player:GetGUIDLow() and p:GetMapId() == s.map
            and (try(player, "GetDistance", p) or 999) <= INVITE_RANGE and not bySeat[p:GetGUIDLow()] then
            send(p, "invite", string.format("%d %s %s", s.id, player:GetName(), (s.course.title:gsub(" ", "_"))))
            say(p, player:GetName() .. " invites you to a round of " .. s.course.title .. ". Open /golf to join.")
            invited = invited + 1
        end
    end
    send(player, "lobby", lobbyText(s))
    say(player, invited > 0 and (s.course.title .. ": invited " .. invited .. " party member" .. (invited == 1 and "" or "s") .. ". Press Tee off when everyone's in.")
        or (s.course.title .. ": press Tee off to start (join a party first to play together)."))
end

local function joinCommand(player, id)
    local s = sessions[tonumber(id or "") or -1]
    if not s or s.state ~= "lobby" then return say(player, "That game has already started or ended.") end
    if #s.players >= MAX_PLAYERS then return say(player, "That game is full.") end
    if bySeat[player:GetGUIDLow()] and bySeat[player:GetGUIDLow()] ~= s.id then leave(player, true) end
    if seatOf(s, player:GetGUIDLow()) then return end
    s.players[#s.players + 1] = seat(player, #s.players)
    bySeat[player:GetGUIDLow()] = s.id
    broadcast(s, "lobby", lobbyText(s))
    note(s, player:GetName() .. " joins the game.")
end

local function goCommand(player)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s then return say(player, "You're not in a game. Start one with .golf start") end
    if s.players[1].guid ~= player:GetGUIDLow() then return say(player, "Only the host can tee off.") end
    if s.state ~= "lobby" then return end
    s.state, s.t0 = "play", now()
    broadcast(s, "session", string.format("%d %s %s %s %s %s", s.id, fmt(s.x), fmt(s.y), fmt(s.z), string.format("%.4f", s.o),
        (s.course.title:gsub(" ", "_"))))
    broadcast(s, "course", s.text)
    startHole(s)
end

local function shotCommand(player, a, p)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s or s.state ~= "play" then return end
    local m = current(s)
    if not m or m.guid ~= player:GetGUIDLow() or s.phase ~= "aim" then return end
    a, p = tonumber(a), tonumber(p)
    if not a or not p or a ~= math.floor(a) or p ~= math.floor(p) or a < 0 or a > 3599 or p < 0 or p > 1000 then return end
    if m.lastShot and now() - m.lastShot < SHOT_GAP then return end
    m.lastShot = now()
    s.phase, s.shotAt = "rolling", now()
    s.stroke = (m.strokes[s.hole] or 0) + 1
    s.shotNo = (s.shotNo or 0) + 1
    s.checks[s.shotNo] = { shooter = m.guid, hashes = {} }
    s.checks[s.shotNo - 4] = nil
    local ph = phase(s)
    -- The round's input log, for replays: every client can re-run it and get the same strokes.
    m.log = m.log or {}
    m.log[s.hole] = m.log[s.hole] or {}
    table.insert(m.log[s.hole], string.format("%d,%d,%d", a, p, ph))
    broadcast(s, "shot", string.format("%s %s %s %s %d %d %d %d %d", m.name, fmt(m.ball.x), fmt(m.ball.y), fmt(m.ball.z), a, p, ph, s.stroke, s.shotNo))
end

local ENDS = { rest = true, holed = true, out = true, water = true }

-- Every member reports every roll's hash; all of them must match the shooter's.
local function compare(s, shotNo, guid, hash)
    local c = s.checks[shotNo]
    if not c then return end
    c.hashes[guid] = hash
    local ref = c.hashes[c.shooter]
    if not ref or c.warned then return end
    for g, h in pairs(c.hashes) do
        if h ~= ref then
            c.warned, s.desync = true, true
            local m = seatOf(s, c.shooter)
            note(s, "Two clients saw " .. (m and m.name or "a") .. "'s shot differently. The shooter's result stands; this round won't count as verified.")
            print(string.format("[ov_golf] desync session %d shot %d: %s vs %s (guid %d)", s.id, shotNo, ref, h, g))
            return
        end
    end
end

local function restCommand(player, shotNo, kind, x, y, z, hash)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s or s.state ~= "play" then return end
    shotNo, x, y, z = tonumber(shotNo), tonumber(x), tonumber(y), tonumber(z)
    if not shotNo or not ENDS[kind] or not x or not y or not z or type(hash) ~= "string" or not hash:match("^%x+$") or #hash > 16 then return end
    if math.abs(x) > MAX_COORD or math.abs(y) > MAX_COORD or math.abs(z) > MAX_COORD then return end
    local guid = player:GetGUIDLow()
    if not seatOf(s, guid) then return end
    compare(s, shotNo, guid, hash)
    local m = current(s)
    -- Only the shooter's report moves the game on, and only for the shot in flight.
    if guid ~= m.guid or s.phase ~= "rolling" or shotNo ~= s.shotNo then return end
    finishShot(s, kind, x, y, z)
end

local function skipCommand(player)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s or s.state ~= "play" then return end
    if s.players[1].guid ~= player:GetGUIDLow() then return say(player, "Only the host can skip a turn.") end
    local m = current(s)
    local idle = now() - (s.phase == "rolling" and s.shotAt or s.turnAt or now())
    if idle < IDLE_SKIP then return say(player, "Give them " .. (IDLE_SKIP - idle) .. " more seconds.") end
    note(s, m.name .. "'s turn is skipped.")
    m.irregular = true
    m.strokes[s.hole] = capFor(s.course.holes[s.hole].par)
    m.done = true
    nextTurn(s)
end

local function slug(s) return ((s or ""):lower():gsub("[^%w]", "")):sub(1, 20) end

local function publishCommand(player, text)
    text = cleanText(text)
    if #text < 20 then return say(player, "Nothing to publish: build a course in the editor first.") end
    if #text > MAX_COURSE_TEXT then return say(player, "That course is too big to publish (14 KB at most).") end
    local c, why = readCourse(text)
    if not c then return say(player, "That course can't be published: " .. tostring(why)) end
    local guid, name = player:GetGUIDLow(), player:GetName()
    local key = (slug(name) .. "_" .. slug(c.title)):sub(1, 32)
    if key:match("^_") or key:match("_$") then return say(player, "Give the course a title first.") end
    local mine, replacing = 0, byKey[key] ~= nil
    for _, e in ipairs(COURSES) do if e.guid == guid then mine = mine + 1 end end
    if not replacing and mine >= MAX_PUBLISHED then
        return say(player, "You have " .. MAX_PUBLISHED .. " courses published; re-publish one of them by its title to replace it.")
    end
    local entry = addCourse(key, text, name, guid)
    if not entry then return say(player, "That course can't be published.") end
    exec(string.format("REPLACE INTO mod_golf_courses (ckey, author_guid, author, title, text, updated_at) VALUES ('%s', %d, '%s', '%s', '%s', %d)",
        key, guid, name:gsub("[^%w]", ""), c.title:gsub("[^%w %-!&%.]", ""), text, now()))
    say(player, string.format("%s %s: everyone on this realm can play it from /golf (%d holes).", c.title,
        replacing and "updated" or "published", #c.holes))
    send(player, "published", key)
end

local function unpublishCommand(player, key)
    if (tonumber(try(player, "GetGMRank")) or 0) <= 0 then return say(player, "Only a GM can take a course down.") end
    local e = byKey[key or ""]
    if not e or not e.guid then return say(player, "No published course called '" .. tostring(key) .. "'.") end
    for i, c in ipairs(COURSES) do if c.key == key then table.remove(COURSES, i) break end end
    byKey[key] = nil
    exec(string.format("DELETE FROM mod_golf_courses WHERE ckey = '%s'", key:gsub("[^%w_]", "")))
    say(player, "Taken down: " .. key)
end

-- The course's best rounds, one per character: id,name,strokes,verified,players;...
local function topCommand(player, key)
    key = (key or ""):gsub("[^%w_]", "")
    if not byKey[key] then return send(player, "top", key .. "\t") end
    local rows, seen = {}, {}
    if CharDBQuery then
        local ok, q = pcall(CharDBQuery, string.format(
            "SELECT id, name, strokes, verified, players FROM mod_golf_runs WHERE course = '%s' ORDER BY strokes ASC, played_at ASC LIMIT 60", key))
        if ok and q then
            repeat
                local name = q:GetString(1)
                if not seen[name] and #rows < 10 then
                    seen[name] = true
                    rows[#rows + 1] = string.format("%d,%s,%d,%d,%d", q:GetUInt32(0), name, q:GetUInt32(2), q:GetUInt32(3), q:GetUInt32(4))
                end
            until not q:NextRow()
        end
    end
    send(player, "top", key .. "\t" .. table.concat(rows, ";"))
end

-- A round's inputs and its course, for the client to play back (and so check) on its own.
local function replayCommand(player, id)
    id = tonumber(id or "")
    if not id or not CharDBQuery then return end
    local ok, q = pcall(CharDBQuery, string.format("SELECT name, course, strokes, inputs FROM mod_golf_runs WHERE id = %d", id))
    if not ok or not q then return say(player, "That round isn't on record.") end
    local key = q:GetString(1)
    local entry = byKey[key]
    if not entry then return say(player, "That round's course is no longer on this realm.") end
    send(player, "replay", string.format("%d %s %d\n%s\n%s", id, q:GetString(0), q:GetUInt32(2), q:GetString(3), entry.text))
end

-- Rounds being played near you, to watch: id,host,title,hole,players;...
local function liveCommand(player)
    local rows = {}
    for id, s in pairs(sessions) do
        if s.state == "play" and s.map == player:GetMapId() then
            local dx, dy = s.x - player:GetX(), s.y - player:GetY()
            if dx * dx + dy * dy <= 150 * 150 then
                rows[#rows + 1] = string.format("%d,%s,%s,%d,%d", id, s.players[1].name, (s.course.title:gsub("[,;]", "")), s.hole, #s.players)
            end
        end
    end
    send(player, "live", table.concat(rows, ";"))
end

-- Watch a round: the course, the hole and every roll, but no turns.
local function watchCommand(player, id)
    local s = sessions[tonumber(id or "") or -1]
    if not s or s.state ~= "play" then return say(player, "That round has ended.") end
    local guid = player:GetGUIDLow()
    if bySeat[guid] then return say(player, "Leave your own game first.") end
    if byWatch[guid] then stopWatching(player) end
    if #s.watchers >= 16 then return say(player, "That round has enough spectators.") end
    s.watchers[#s.watchers + 1] = { guid = guid, name = player:GetName(), player = player }
    byWatch[guid] = s.id
    local h = s.course.holes[s.hole]
    send(player, "session", string.format("%d %s %s %s %s %s", s.id, fmt(s.x), fmt(s.y), fmt(s.z), string.format("%.4f", s.o), (s.course.title:gsub(" ", "_"))))
    send(player, "course", s.text)
    send(player, "watching", tostring(s.id))
    send(player, "hole", string.format("%d %d %s", s.hole, h.par, h.name))
    send(player, "score", scoreText(s))
    if s.lastTurn then send(player, "turn", s.lastTurn) end
    for _, e in ipairs(members(s)) do send(e.player, "msg", player:GetName() .. " is watching.") end
end

local function coursesText()
    local parts = {}
    for _, e in ipairs(COURSES) do
        if e.course then
            local par = 0
            for _, h in ipairs(e.course.holes) do par = par + h.par end
            parts[#parts + 1] = string.format("%s,%s,%d,%d,%s", e.key, (e.course.title:gsub("[,;]", "")), #e.course.holes, par,
                ((e.author or "Leyline"):gsub("[,;]", "")))
        end
    end
    return table.concat(parts, ";")
end

local function run(player, text)
    local word, a, b, c, d, e, f = (text or ""):match("^(%S*)%s*(%S*)%s*(%S*)%s*(%S*)%s*(%S*)%s*(%S*)%s*(%S*)")
    word = (word or ""):lower()
    if word == "courses" then
        send(player, "courses", coursesText())
        local names = {}
        for _, e2 in ipairs(COURSES) do if e2.course then names[#names + 1] = e2.key .. " (" .. e2.course.title .. ")" end end
        say(player, "Courses: " .. table.concat(names, ", "))
    elseif word == "start" then startCommand(player, a)
    elseif word == "join" then joinCommand(player, a)
    elseif word == "go" then goCommand(player)
    elseif word == "leave" then leave(player)
    elseif word == "shot" then shotCommand(player, a, b)
    elseif word == "rest" then restCommand(player, a, b, c, d, e, f)
    elseif word == "skip" then skipCommand(player)
    elseif word == "top" then topCommand(player, a)
    elseif word == "live" then liveCommand(player)
    elseif word == "watch" then watchCommand(player, a)
    elseif word == "replay" then replayCommand(player, a)
    elseif word == "unpublish" then unpublishCommand(player, a)
    else
        say(player, ".golf courses | start [course] | join <id> | go | leave | skip | unpublish <key> (GM). Or open /golf (browser client).")
    end
end

-- The window's channel: each message name is the command.
for _, name in ipairs({ "courses", "start", "join", "go", "leave", "shot", "rest", "skip", "top", "replay", "live", "watch" }) do
    OVMod.On(MOD, name, function(player, data) run(player, name .. " " .. (data or "")) end)
end
-- A course from the editor arrives whole (ov_modapi reassembles its parts).
OVMod.On(MOD, "publish", function(player, data) publishCommand(player, data) end)

-- A shooter who never reports (closed the tab mid-roll) doesn't stall the game.
if CreateLuaEvent then
    CreateLuaEvent(function()
        for _, s in pairs(sessions) do
            if s.state == "play" and s.phase == "rolling" and now() - (s.shotAt or now()) > REST_WAIT then
                local m = current(s)
                note(s, m.name .. "'s ball was lost in the post; it counts where it was hit from.")
                m.irregular = true
                finishShot(s, "rest", m.ball.x, m.ball.y, m.ball.z)
            elseif s.state == "lobby" and now() - s.t0 > 600 then
                endSession(s, "The game wasn't started in time.")
            end
        end
    end, 5000, 0)
end

RegisterPlayerEvent(42, function(event, player, command)
    local rest = (command or ""):match("^golf%s*(.*)$")
    if not rest then return end
    run(player, rest)
    return false
end)
RegisterPlayerEvent(4, function(event, player) leave(player, false) end)
RegisterPlayerEvent(28, function(event, player) leave(player, false) end)

-- For the tests.
return { sessions = sessions, bySeat = bySeat, readCourse = readCourse, COURSES = COURSES, run = run }
