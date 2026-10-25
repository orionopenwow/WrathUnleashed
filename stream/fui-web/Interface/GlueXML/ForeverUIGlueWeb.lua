-- WrathUnleashed: Forever UI's character select, fixed for the browser client (v2).
-- Runs after ForeverUIGlue.xml (GlueXML.toc, fui-overlay.py). Numbers are Forever UI's glue units.
--
-- Scope, on purpose: the character select screen only. No hook on AccountLogin, RealmList,
-- RealmWizard, GlueParent or any glue screen's OnShow/OnUpdate; nothing runs during the login ->
-- character select switch (GlueScreenExit's fade). Every step is pcall-guarded: a failure leaves
-- Forever UI's own layout as it was.
--
--   1. The expansion logo on character select is hidden (Forever UI already hides the create
--      screen's; the login screen is never shown to a page-signed-in player).
--   2. Top bar (REALMS | MENU | ADDONS): evenly sized buttons. In the browser GetTextWidth is 0
--      while ForeverUIGlueCharacterSelect.lua loads, so each button was 70 wide and its label
--      ran into the divider. Re-measured once the screen is up, by a watcher frame inside the
--      screen (it only ticks while character select is visible, and stops after 3 s).
--   3. Layout: one 20-unit margin, the list clear of the top bar and of "Toggle Character List",
--      the name clear of Enter World, the bottom row on one centre line.

local G = ForeverUIGlue
if type(G) ~= "table" or not CharacterSelect or not CharacterSelectUI then return end

local function try(f, ...)
	local ok = pcall(f, ...)
	return ok
end

local ui = CharacterSelectUI
local MARGIN, ROW = 20, 33

-- ---------- 1. Logo (a texture: no script fires)

try(function()
	if CharacterSelectLogo then
		CharacterSelectLogo:SetAlpha(0)
		CharacterSelectLogo:Hide()
	end
end)

-- ---------- 2. Top bar

local MIN_W, PAD, CAP_SHIFT = 150, 64, 12
local nav = ForeverUICharacterSelectNavBar
local tray = nav and nav:GetChildren()

local function navButtons()
	local out = {}
	if not tray then return out end
	for _, b in ipairs({ tray:GetChildren() }) do
		if b.GetText and b:IsShown() then out[#out + 1] = b end
	end
	return out
end

local function labelWidth(b)
	local w = 0
	local fs = b:GetFontString()
	if fs then w = fs:GetStringWidth() or 0 end
	return w
end

local navWidth
-- measured: false while the font is not drawn yet (every label 0): an estimate is used then
local function arrangeNav()
	local shown = navButtons()
	if #shown == 0 then return true end
	local w, measured = MIN_W, true
	for _, b in ipairs(shown) do
		local lw = labelWidth(b)
		if lw <= 0 then
			measured = false
			lw = string.len(b:GetText() or "") * 11
		end
		w = math.max(w, math.ceil(lw + PAD))
	end
	local stale = (w ~= navWidth)
	for _, b in ipairs(shown) do
		if math.abs((b:GetWidth() or 0) - w) > 0.5 then stale = true end
	end
	if stale then
		navWidth = w
		local x = 0
		for i, b in ipairs(shown) do
			b:SetWidth(w)
			b:ClearAllPoints()
			b:SetPoint("TOPLEFT", tray, "TOPLEFT", x, 0)
			x = x + w
			local fs = b:GetFontString()
			if fs then
				local dx = 0
				if #shown > 1 and i == 1 then dx = CAP_SHIFT end
				if #shown > 1 and i == #shown then dx = -CAP_SHIFT end
				fs:ClearAllPoints()
				fs:SetPoint("CENTER", b, "CENTER", dx, 2)
			end
		end
		tray:SetWidth(x)
	end
	return measured
end

-- ---------- 3. Layout (anchors only; Forever UI's own OnShow fit then sees them)

local function layout()
	local list, collapse = CharacterSelectCharacterFrame, ForeverUICharacterSelectListToggle
	local enter, back = CharSelectEnterWorldButton, CharacterSelectBackButton
	local eye, name = ForeverUICharacterSelectVisibilityToggle, CharSelectCharacterName
	if collapse then
		collapse:ClearAllPoints()
		collapse:SetPoint("BOTTOMRIGHT", ui, "BOTTOMRIGHT", -MARGIN, ROW - 25)
	end
	if list and collapse then
		-- the bronze frame hangs 9 out at the sides, 15 above and below
		list:ClearAllPoints()
		list:SetPoint("TOPRIGHT", ui, "TOPRIGHT", -(MARGIN + 9), -96)
		list:SetPoint("BOTTOMRIGHT", collapse, "TOPRIGHT", -9, 30)
	end
	if back then
		back:SetWidth(160)
		back:SetHeight(42)
		back:ClearAllPoints()
		back:SetPoint("BOTTOMLEFT", ui, "BOTTOMLEFT", MARGIN, ROW - 21)
	end
	if eye and back then
		eye:ClearAllPoints()
		eye:SetPoint("LEFT", back, "RIGHT", 6, 0)
	end
	if enter then
		-- the rotate buttons hang 4 into Enter World's bottom: their 48 centred on ROW
		enter:ClearAllPoints()
		enter:SetPoint("BOTTOM", ui, "BOTTOM", 0, ROW + 20)
		if name then
			name:ClearAllPoints()
			name:SetPoint("BOTTOM", enter, "TOP", 0, 14)
		end
	end
end

try(layout)
try(arrangeNav)

-- ---------- Watcher: re-measures the top bar while character select is up, then stops

local watch = CreateFrame("Frame", nil, ui)
watch:Hide()
watch.left = 0
watch:SetScript("OnUpdate", function(self, elapsed)
	self.left = self.left - (elapsed or 0.1)
	local ok, measured = pcall(arrangeNav)
	if (ok and measured) or self.left <= 0 then self:Hide() end
end)
-- Shown from Forever UI's own UpdateCharacterList hook point: after the list is in, never inside
-- the screen switch itself.
if G.HookFunction then
	local function arm()
		watch.left = 3
		watch:Show()
	end
	try(G.HookFunction, "UpdateCharacterList", arm)
	-- Forever UI shows or hides ADDONS here: the widths follow on the watcher's next tick.
	try(G.HookFunction, "UpdateAddonButton", arm)
end
