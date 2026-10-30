-- Leyline Modes: writes the creator API docs from the API table.
--
--   lua5.1 tools/creator-api/gen.lua            writes docs/CREATOR-API.md and docs/creator-api.html
--   lua5.1 tools/creator-api/gen.lua --check    exits 1 if either file is out of date (the tests run this)
--
-- Run from the repo root. The source is stream/fui-web/Interface/AddOns/WrathUnleashedUI/ModeAPI.lua (the API
-- table the sandbox is built from) and ModeExamples.lua (the two example modes). Both outputs come from one
-- document model below, so the Markdown and the HTML page always say the same thing. The HTML page is one
-- static file with no outside requests, for the portal to serve as it is.
--
-- As a library (the tests): CREATOR_API_GEN_LIB = true; local G = dofile("tools/creator-api/gen.lua")
--   G.load(root) -> API, EXAMPLES      G.markdown(API, EXAMPLES) -> text      G.html(API, EXAMPLES) -> text

local G = {}
G.ADDON = "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
G.MD = "docs/CREATOR-API.md"
G.HTML = "docs/creator-api.html"

function G.load(root)
    root = root or "."
    local API = dofile(root .. "/" .. G.ADDON .. "/ModeAPI.lua")
    local EX = dofile(root .. "/" .. G.ADDON .. "/ModeExamples.lua")
    return API, EX
end

-- ------------------------------------------------------------------ the document model
-- Blocks: { "h1"|"h2"|"h3", text, id } { "p", text } { "ul", { items } } { "table", { head }, { rows } } { "code", text }
-- Inline text may use `code` and **bold**.

local function since(x, API) return x.since and x.since > 1 and (" *(new in " .. x.since .. ")*") or "" end

local function slug(s) return (s:lower():gsub("[^%w]+", "-"):gsub("^%-", ""):gsub("%-$", "")) end

function G.model(API, EX)
    local D = {}
    local function add(...) D[#D + 1] = { ... } end
    add("h1", "Leyline Modes: the creator API", "top")
    add("p", "Version " .. API.VERSION .. ". A **mode** is one Lua script: a small game that a host plays with their party. "
        .. "Write one in game with `/modes edit`. This page lists everything a script can use.")
    add("h2", "How a script runs", "how")
    add("ul", {
        "**The host's client runs the script**, in a sandbox. It has the safe parts of `string`, `math` and `table` and the API below. It has no game UI, no chat, no network and no way to load more code.",
        "**Everyone else only draws what the host sends**, and sends back the keys the mode asked for. Joining a mode never runs its code on your client.",
        "**Every call into the script has a time budget** of " .. API.GUARD_MS .. " ms: loading it, each callback and each timer. A script that runs too long, such as an endless loop, is stopped. Only that mode stops, and the editor shows the line it was on.",
        "**Coordinates** are yards, in a frame placed where the host stood: +x is right, +y is up and +z is forward. Build around `0, 0, 0`.",
        "**Publishing:** a GM reviews every published mode before others can see it. You can always play and host your own.",
    })
    add("h2", "The script editor", "editor")
    add("ul", {
        "`/modes edit` opens it. It has line numbers and keyword colours (**Colours** turns them off).",
        "**Play** runs a copy of the script here, on your own. **Play Here** hosts a copy where you stand and invites your party nearby. The realm checks it first.",
        "**Stop** ends the test and brings the editor back. A test never changes your text or your saved draft.",
        "**Save** keeps the script in this browser and on your account. **Save while a test runs to hot-reload it**: the new script takes over, and State values and scores are kept. The old shapes go, and `OnStart` runs again. If the new script has an error, the old one keeps running.",
        "**The console** lists errors with their line. Click one to jump to that line. `print` output shows there too.",
        "**Check** looks for problems without running anything. **Publish** saves, then sends the script for GM review.",
        "**Start from** opens the template, the built-in modes or the two examples below. **API** lists the functions in the console.",
    })
    add("h2", "Settings", "settings")
    local rows = {}
    for _, f in ipairs(API.FIELDS) do rows[#rows + 1] = { "`" .. f.name .. " = " .. f.value .. "`", f.about .. since(f) } end
    add("table", { "Setting", "What it does" }, rows)
    add("p", "Keys a mode can ask for: " .. table.concat((function() local l = {} for _, k in ipairs(API.KEYS) do l[#l + 1] = "`" .. k .. "`" end return l end)(), " ") .. ".")
    add("h2", "Callbacks", "callbacks")
    add("p", "Define these as globals. The host calls them, each under the time budget.")
    rows = {}
    for _, c in ipairs(API.CALLBACKS) do rows[#rows + 1] = { "`function " .. c.name .. "(" .. c.args .. ")`", c.about .. since(c) } end
    add("table", { "Callback", "When" }, rows)
    add("h2", "Functions", "functions")
    for _, ns in ipairs(API.NAMESPACES) do
        add("h3", ns.name, slug(ns.name))
        add("p", ns.about)
        rows = {}
        for _, f in ipairs(ns.fns) do
            local call = ns.name .. "." .. f.name .. (f.args:sub(1, 1) == "{" and f.args or ("(" .. f.args .. ")"))
            rows[#rows + 1] = { "`" .. call .. "`", f.returns and ("`" .. f.returns .. "`") or "", f.about .. since(f) }
        end
        add("table", { "Call", "Returns", "What it does" }, rows)
    end
    add("h3", "Other globals", "globals")
    rows = {}
    for _, f in ipairs(API.GLOBALS) do
        rows[#rows + 1] = { "`" .. f.name .. "(" .. f.args .. ")`", f.returns and ("`" .. f.returns .. "`") or "", f.about .. since(f) }
    end
    add("table", { "Call", "Returns", "What it does" }, rows)
    add("h3", "Devices (device modes only)", "devices")
    add("p", "A mode that uses `Devices.Run` gets this table too. See MODES.md for the devices and wires.")
    rows = {}
    for _, f in ipairs(API.DEVICES) do rows[#rows + 1] = { "`Devices." .. f.name .. (f.args:sub(1, 1) == "[" and f.args or ("(" .. f.args .. ")")) .. "`", f.about } end
    add("table", { "Call", "What it does" }, rows)
    add("h2", "The standard library", "stdlib")
    local base = {}
    for _, b in ipairs(API.BASE) do base[#base + 1] = "`" .. b .. "`" end
    local libs = { "Base functions: " .. table.concat(base, " ") .. ". `pcall` can't catch the time budget: a script that catches it is stopped anyway." }
    for _, l in ipairs(API.LIBS) do libs[#libs + 1] = "`" .. l.name .. "`: " .. l.about end
    add("ul", libs)
    add("h2", "Limits", "limits")
    rows = {}
    for _, l in ipairs(API.LIMITS) do rows[#rows + 1] = { tostring(API[l[1]]), l[2] } end
    add("table", { "Limit", "What" }, rows)
    add("p", "The realm also limits how often you can save (one draft every 2 s), test with Play Here (one every 5 s) and publish (one every 10 s).")
    add("h2", "Not available", "blocked")
    local bl = {}
    for _, b in ipairs(API.BLOCKED) do bl[#bl + 1] = "`" .. b .. "`" end
    add("p", "A script that names one of these is refused before it runs, with the line: " .. table.concat(bl, " ")
        .. ". So is `string.dump`, and `s:rep(n)` (write `string.rep(s, n)`, which is capped). Nothing else from the game is in the sandbox either.")
    add("h2", "Examples", "examples")
    add("p", "Both use only the API on this page. Open them in the editor with **Start from**, or play them with `/modes collect` and `/modes hill`.")
    for _, ex in ipairs(EX) do
        add("h3", ex.title, slug(ex.title))
        add("code", ex.text)
    end
    return D
end

-- ------------------------------------------------------------------ Markdown

function G.markdown(API, EX)
    local out = {}
    local function w(s) out[#out + 1] = s end
    for _, b in ipairs(G.model(API, EX)) do
        local k = b[1]
        if k == "h1" then w("# " .. b[2]); w("")
            w("<!-- Made by tools/creator-api/gen.lua from " .. G.ADDON .. "/ModeAPI.lua. Edit that file, then run the tool. -->"); w("")
        elseif k == "h2" then w("## " .. b[2]); w("")
        elseif k == "h3" then w("### " .. b[2]); w("")
        elseif k == "p" then w(b[2]); w("")
        elseif k == "ul" then for _, it in ipairs(b[2]) do w("- " .. it) end; w("")
        elseif k == "table" then
            w("| " .. table.concat(b[2], " | ") .. " |")
            local sep = {}
            for i = 1, #b[2] do sep[i] = "---" end
            w("|" .. table.concat(sep, "|") .. "|")
            for _, r in ipairs(b[3]) do
                local cells = {}
                for i, c in ipairs(r) do cells[i] = (c:gsub("|", "\\|")) end
                w("| " .. table.concat(cells, " | ") .. " |")
            end
            w("")
        elseif k == "code" then w("```lua"); w((b[2]:gsub("\n$", ""))); w("```"); w("")
        end
    end
    return (table.concat(out, "\n"):gsub("\n+$", "\n"))
end

-- ------------------------------------------------------------------ HTML (one static page, no outside requests)

local function esc(s) return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;")) end
local function inline(s)
    s = esc(s)
    s = s:gsub("`([^`]+)`", "<code>%1</code>")
    s = s:gsub("%*%*(.-)%*%*", "<strong>%1</strong>")
    s = s:gsub("%*(%(new in %d+%))%*", '<span class="new">%1</span>')
    return s
end

local CSS = [[
:root { --bg: #f7f6fb; --fg: #1d1b26; --muted: #5d5a6e; --card: #ffffff; --line: #dcd8ea; --accent: #6b4fd8; --code: #efecf8; --new: #1f7a4d; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #12111a; --fg: #e9e6f5; --muted: #a29fb6; --card: #1b1a26; --line: #2f2c40; --accent: #b39cff; --code: #24223a; --new: #6fd3a0; } }
:root[data-theme="dark"] { --bg: #12111a; --fg: #e9e6f5; --muted: #a29fb6; --card: #1b1a26; --line: #2f2c40; --accent: #b39cff; --code: #24223a; --new: #6fd3a0; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.9rem; margin: 0 0 8px; }
h2 { font-size: 1.35rem; margin: 40px 0 12px; padding-top: 8px; border-top: 1px solid var(--line); }
h3 { font-size: 1.1rem; margin: 28px 0 8px; color: var(--accent); }
p, li { color: var(--fg); }
a { color: var(--accent); }
nav { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 16px 0 8px; font-size: .92rem; }
code { font: .88em/1.4 ui-monospace, "DejaVu Sans Mono", Menlo, Consolas, monospace; background: var(--code); padding: 1px 5px; border-radius: 4px; }
pre { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 14px; overflow-x: auto; }
pre code { background: none; padding: 0; font-size: .84rem; }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: var(--card); border: 1px solid var(--line); border-radius: 8px; font-size: .94rem; }
th, td { text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; font-size: .85rem; }
td code { white-space: nowrap; }
.new { color: var(--new); font-style: normal; font-size: .85em; }
.muted { color: var(--muted); font-size: .9rem; }
]]

function G.html(API, EX)
    local out = {}
    local function w(s) out[#out + 1] = s end
    local model = G.model(API, EX)
    w("<!doctype html>")
    w('<html lang="en">')
    w("<head>")
    w('<meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width, initial-scale=1">')
    w("<title>Creator API</title>")
    w('<meta name="description" content="Leyline Modes: everything a mode script can use, version ' .. API.VERSION .. '.">')
    w("<style>" .. CSS .. "</style>")
    w("</head>")
    w("<body>")
    w("<main>")
    for _, b in ipairs(model) do
        local k = b[1]
        if k == "h1" then
            w('<h1 id="' .. b[3] .. '">' .. inline(b[2]) .. "</h1>")
            w('<p class="muted">Made from ModeAPI.lua by tools/creator-api/gen.lua.</p>')
            local links = {}
            for _, x in ipairs(model) do if x[1] == "h2" then links[#links + 1] = '<a href="#' .. x[3] .. '">' .. inline(x[2]) .. "</a>" end end
            w("<nav>" .. table.concat(links, "") .. "</nav>")
        elseif k == "h2" or k == "h3" then w("<" .. k .. ' id="' .. b[3] .. '">' .. inline(b[2]) .. "</" .. k .. ">")
        elseif k == "p" then w("<p>" .. inline(b[2]) .. "</p>")
        elseif k == "ul" then
            w("<ul>")
            for _, it in ipairs(b[2]) do w("<li>" .. inline(it) .. "</li>") end
            w("</ul>")
        elseif k == "table" then
            w('<div class="table"><table>')
            local h = {}
            for _, c in ipairs(b[2]) do h[#h + 1] = "<th>" .. inline(c) .. "</th>" end
            w("<thead><tr>" .. table.concat(h) .. "</tr></thead>")
            w("<tbody>")
            for _, r in ipairs(b[3]) do
                local cells = {}
                for _, c in ipairs(r) do cells[#cells + 1] = "<td>" .. inline(c) .. "</td>" end
                w("<tr>" .. table.concat(cells) .. "</tr>")
            end
            w("</tbody></table></div>")
        elseif k == "code" then w("<pre><code>" .. esc((b[2]:gsub("\n$", ""))) .. "</code></pre>")
        end
    end
    w("</main>")
    w("</body>")
    w("</html>")
    return table.concat(out, "\n") .. "\n"
end

-- ------------------------------------------------------------------ the command

local function read(path)
    local f = io.open(path, "rb")
    if not f then return nil end
    local s = f:read("*a")
    f:close()
    return s
end

function G.main(args)
    local check = false
    for _, a in ipairs(args or {}) do if a == "--check" then check = true end end
    local API, EX = G.load(".")
    local want = { [G.MD] = G.markdown(API, EX), [G.HTML] = G.html(API, EX) }
    local stale = 0
    for _, path in ipairs({ G.MD, G.HTML }) do
        if check then
            if read(path) ~= want[path] then print(path .. " is out of date: run lua5.1 tools/creator-api/gen.lua"); stale = stale + 1 end
        else
            local f = assert(io.open(path, "wb"))
            f:write(want[path])
            f:close()
            print("wrote " .. path)
        end
    end
    return stale == 0
end

if not rawget(_G, "CREATOR_API_GEN_LIB") then
    local ok = G.main(arg)
    os.exit(ok and 0 or 1)
end
return G
