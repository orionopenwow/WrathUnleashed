-- Style.lua (3.3.5a API): the Leyline look for every WrathUnleashedUI window, the same palette as the launcher and
-- the website (launcher/ui/style.css): a dark slate window (#181b23, title bar #11131a), a 1px border (#2b3040),
-- accent blue #5b8def, violet #8b5cf6, text #e6e8ef, muted #9aa3b5, and the Leyline mark (the crystal in its swirl)
-- in each window's title bar.
--
-- Everything is drawn with solid-colour textures (Texture:SetTexture(r, g, b, a)), which the client draws itself, so
-- a window looks right even where a texture file can't load. The backdrop uses our own 8x8 white file
-- (Media\white8x8.tga) on top of that; the mark is Media\leyline-mark-64.tga / -128.tga, made from the website's
-- Leyline art by stream/fui-web/make-wuui-media.py. No game textures, no new fonts (the client's own).
--
--   S.Window(frame, title, opts)    the window: fill, border, title bar with the mark and the title, close button
--                                   (opts.noClose; opts.titleY). Returns the title FontString.
--   S.Button(parent, text, w, onClick, kind, point...)   our button: kind "primary" (accent), "ghost" (default),
--                                   "danger"; normal / hover / pressed / disabled states. h = 22.
--   S.Box(frame, alpha)             an inner panel (cards, boxes): the darker fill and the border.
--   S.Input(parent, w, h)           an EditBox in the same look.
--   S.Close(parent)                 the title bar's close button (hides the parent).
--   S.Tab(button, on)               a tab button's selected look.
--   S.Recolor(frame)                after a window is built: gold and white texts become the palette's text colours.
--   S.Hex(name)                     "|cffRRGGBB" for a palette colour, for coloured words in text.

local W = WrathUnleashedUI
local S = {}
W.Style = S

local MEDIA = "Interface\\AddOns\\WrathUnleashedUI\\Media\\"
S.MEDIA = MEDIA
S.WHITE = MEDIA .. "white8x8"
S.MARK = MEDIA .. "leyline-mark-64"
S.MARK_BIG = MEDIA .. "leyline-mark-128"
S.TITLE_H = 30

local function rgb(hex, a)
    return { tonumber(hex:sub(1, 2), 16) / 255, tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255, a or 1 }
end
S.C = {
    bg = rgb("181b23", 0.97), bg2 = rgb("11131a", 0.98), border = rgb("2b3040"), accent = rgb("5b8def"),
    accentHi = rgb("7aa3f3"), accentLo = rgb("4a78d4"), violet = rgb("8b5cf6"), text = rgb("e6e8ef"),
    muted = rgb("9aa3b5"), ghost = rgb("222632"), ghostHi = rgb("2b3040"), ghostLo = rgb("1a1d27"),
    danger = rgb("d9534f"), dangerHi = rgb("e46c68"), dangerLo = rgb("b8423e"), off = rgb("1d2029"),
    offText = rgb("5d6474"), ok = rgb("4cc38a"), warn = rgb("e5b454"),
}
S.HEX = { accent = "5b8def", violet = "8b5cf6", text = "e6e8ef", muted = "9aa3b5", ok = "4cc38a", warn = "e5b454",
    danger = "e46c68" }
function S.Hex(name) return "|cff" .. (S.HEX[name] or S.HEX.text) end

local function unpackC(c) return c[1], c[2], c[3], c[4] end
S.Unpack = unpackC

-- A solid-colour texture on a layer.
local function solid(frame, layer, c, sub)
    local t = frame:CreateTexture(nil, layer or "BACKGROUND", nil, sub)
    t:SetTexture(unpackC(c))
    return t
end
S.Solid = solid

-- A 1px border inside the frame's edges (four strips).
local function border(frame, c, layer)
    c = c or S.C.border
    local e = {}
    for i, side in ipairs({ { "TOPLEFT", "TOPRIGHT", 0, 1 }, { "BOTTOMLEFT", "BOTTOMRIGHT", 0, 1 },
                            { "TOPLEFT", "BOTTOMLEFT", 1, 0 }, { "TOPRIGHT", "BOTTOMRIGHT", 1, 0 } }) do
        local t = solid(frame, layer or "BORDER", c)
        t:SetPoint(side[1]); t:SetPoint(side[2])
        if side[3] == 1 then t:SetWidth(1) else t:SetHeight(1) end
        e[i] = t
    end
    return e
end
S.Border = border

local function backdrop(frame, fill)
    if not frame.SetBackdrop then return end
    frame:SetBackdrop({ bgFile = S.WHITE, edgeFile = S.WHITE, tile = false, edgeSize = 1,
        insets = { left = 1, right = 1, top = 1, bottom = 1 } })
    if frame.SetBackdropColor then frame:SetBackdropColor(unpackC(fill)) end
    if frame.SetBackdropBorderColor then frame:SetBackdropBorderColor(unpackC(S.C.border)) end
end
S.Backdrop = backdrop

function S.Box(frame, alpha)
    local c = { S.C.bg2[1], S.C.bg2[2], S.C.bg2[3], alpha or 0.9 }
    backdrop(frame, c)
    if not frame.styleFill then
        frame.styleFill = solid(frame, "BACKGROUND", c)
        frame.styleFill:SetPoint("TOPLEFT", 1, -1); frame.styleFill:SetPoint("BOTTOMRIGHT", -1, 1)
        frame.styleBorder = border(frame)
    end
    return frame
end

-- ---------------------------------------------------------------- buttons

local KINDS = {
    primary = { "accent", "accentHi", "accentLo", "text" },
    ghost = { "ghost", "ghostHi", "ghostLo", "text" },
    danger = { "danger", "dangerHi", "dangerLo", "text" },
}

local function paint(b)
    local k = KINDS[b.styleKind] or KINDS.ghost
    local enabled = b.enabled ~= false   -- our Enable / Disable keep it (3.3.5's IsEnabled says 1 or nil)
    local c
    if not enabled then c = S.C.off
    elseif b.stylePressed then c = S.C[k[3]]
    elseif b.styleOver or b.styleOn then c = S.C[k[2]]
    else c = S.C[k[1]] end
    if b.styleBg then b.styleBg:SetTexture(unpackC(c)) end
    if b.styleText then
        local t = enabled and S.C[k[4]] or S.C.offText
        b.styleText:SetTextColor(t[1], t[2], t[3])
    end
    if b.styleEdge then
        local e = (b.styleKind == "ghost" and enabled) and (b.styleOn and S.C.accent or S.C.border) or c
        for _, t in ipairs(b.styleEdge) do t:SetTexture(unpackC(e)) end
    end
end
S.Paint = paint

-- Our button (no template). Keeps the Button API the windows use: SetText / GetText / Enable / Disable / SetScript.
function S.Button(parent, text, w, onClick, kind, ...)
    local b = CreateFrame("Button", nil, parent)
    b:SetWidth(w or 90); b:SetHeight(22)
    b.styleKind = KINDS[kind] and kind or "ghost"
    b.styleBg = solid(b, "BACKGROUND", S.C.ghost)
    b.styleBg:SetPoint("TOPLEFT", 1, -1); b.styleBg:SetPoint("BOTTOMRIGHT", -1, 1)
    b.styleEdge = border(b, S.C.border, "BORDER")
    local fs = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    fs:SetPoint("LEFT", 6, 0); fs:SetPoint("RIGHT", -6, 0)
    fs:SetJustifyH("CENTER")
    if b.SetFontString then b:SetFontString(fs) end
    b.styleText = fs
    -- SetText / GetText go through our FontString (SetFontString does it too; this is for clients without it)
    local setText = b.SetText
    b.SetText = function(self, t)
        fs:SetText(t)
        if setText then pcall(setText, self, t) end
        self.text = t
    end
    b.GetText = function() return fs:GetText() end
    local enable, disable = b.Enable, b.Disable
    b.Enable = function(self, ...) if enable then enable(self, ...) end; self.enabled = true; paint(self) end
    b.Disable = function(self, ...) if disable then disable(self, ...) end; self.enabled = false; paint(self) end
    b:SetScript("OnEnter", function(self) self.styleOver = true; paint(self) end)
    b:SetScript("OnLeave", function(self) self.styleOver, self.stylePressed = nil, nil; paint(self) end)
    b:SetScript("OnMouseDown", function(self) self.stylePressed = true; paint(self) end)
    b:SetScript("OnMouseUp", function(self) self.stylePressed = nil; paint(self) end)
    b:SetText(text or "")
    if select("#", ...) > 0 then b:SetPoint(...) end
    if onClick then b:SetScript("OnClick", onClick) end
    paint(b)
    return b
end

function S.SetKind(b, kind)
    if b and b.styleBg then b.styleKind = KINDS[kind] and kind or "ghost"; paint(b) end
end

-- A tab button's selected state (an accent edge and the hover fill).
function S.Tab(b, on)
    if not b then return end
    if b.styleBg then b.styleOn = on and true or nil; paint(b) elseif b.SetAlpha then b:SetAlpha(on and 1 or 0.6) end
end

function S.Close(parent)
    local b = S.Button(parent, "x", 22, function(self) self:GetParent():Hide() end, "ghost", "TOPRIGHT", -5, -4)
    b:SetHeight(22)
    return b
end

function S.Input(parent, w, h)
    local e = CreateFrame("EditBox", nil, parent)
    e:SetWidth(w or 200); e:SetHeight(h or 22)
    if e.SetFontObject then e:SetFontObject(ChatFontNormal or GameFontHighlightSmall) end
    if e.SetTextInsets then e:SetTextInsets(6, 6, 0, 0) end
    S.Box(e, 1)
    e:SetAutoFocus(false)
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end

-- ---------------------------------------------------------------- windows

function S.Window(frame, title, opts)
    opts = opts or {}
    backdrop(frame, S.C.bg)
    if not frame.styleFill then
        frame.styleFill = solid(frame, "BACKGROUND", S.C.bg)
        frame.styleFill:SetPoint("TOPLEFT", 1, -1); frame.styleFill:SetPoint("BOTTOMRIGHT", -1, 1)
        frame.styleBorder = border(frame)
        local bar = solid(frame, "BORDER", S.C.bg2)
        bar:SetPoint("TOPLEFT", 1, -1); bar:SetPoint("TOPRIGHT", -1, -1); bar:SetHeight(S.TITLE_H)
        local line = solid(frame, "ARTWORK", S.C.border)
        line:SetPoint("TOPLEFT", 1, -S.TITLE_H - 1); line:SetPoint("TOPRIGHT", -1, -S.TITLE_H - 1); line:SetHeight(1)
        -- the accent hairline under the title bar's left part: the launcher's header rule
        local glow = solid(frame, "ARTWORK", S.C.accent, 1)
        glow:SetPoint("TOPLEFT", 1, -S.TITLE_H - 1); glow:SetWidth(64); glow:SetHeight(1)
        local mark = frame:CreateTexture(nil, "ARTWORK")
        mark:SetTexture(S.MARK)
        mark:SetWidth(20); mark:SetHeight(20)
        mark:SetPoint("TOPLEFT", 9, -6)
        frame.styleBar, frame.styleMark = bar, mark
        local fs = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
        fs:SetPoint("LEFT", mark, "RIGHT", 7, 0)
        fs:SetJustifyH("LEFT")
        fs:SetTextColor(S.C.text[1], S.C.text[2], S.C.text[3])
        frame.styleTitle = fs
        -- a child's OnShow runs whenever the window shows: the texts made since take the palette's colours
        local watch = CreateFrame("Frame", nil, frame)
        watch:SetScript("OnShow", function() S.Recolor(frame) end)
        frame.styleWatch = watch
    end
    frame.styleTitle:SetText(title or "")
    if not opts.noClose and not frame.styleClose then frame.styleClose = S.Close(frame) end
    return frame.styleTitle
end

-- Texts in the stock gold (GameFontNormal) or white (GameFontHighlight) take the palette's colours: gold -> text,
-- white -> text, grey (GameFontDisable) -> muted. Coloured words inside a text (|cff...) keep their colour.
local function near(r, g, b, R, G, B) return math.abs(r - R) < 0.06 and math.abs(g - G) < 0.06 and math.abs(b - B) < 0.06 end
local function recolorFS(fs)
    if not fs.GetTextColor or fs.styleKeep then return end
    local r, g, b = fs:GetTextColor()
    if type(r) ~= "number" then return end
    local c
    if near(r, g, b, 1, 0.82, 0) then c = S.C.text
    elseif near(r, g, b, 1, 1, 1) then c = S.C.text
    elseif near(r, g, b, 0.5, 0.5, 0.5) then c = S.C.muted end
    if c then fs:SetTextColor(c[1], c[2], c[3]) end
end
function S.Recolor(frame, depth)
    depth = depth or 0
    if not frame or depth > 8 then return end
    if frame.GetRegions then
        for _, r in ipairs({ frame:GetRegions() }) do
            if type(r) == "table" and r.GetObjectType and r:GetObjectType() == "FontString" then recolorFS(r) end
        end
    end
    if frame.GetChildren then
        for _, c in ipairs({ frame:GetChildren() }) do
            if type(c) == "table" and not c.styleText then S.Recolor(c, depth + 1) end
        end
    end
end

-- A muted helper line (the small grey text under a control).
function S.Muted(fs) if fs and fs.SetTextColor then fs:SetTextColor(S.C.muted[1], S.C.muted[2], S.C.muted[3]); fs.styleKeep = true end return fs end
