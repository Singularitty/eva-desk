-- eva-desk: the Hyprland half of the theme (look, stage gaps, binds, autostart).
-- Load it at the END of hyprland.lua (install.sh adds this line):
--   dofile(os.getenv("HOME") .. "/.local/share/eva-desk/hypr/eva.lua")   -- or /usr/share/eva-desk/hypr/eva.lua
-- Settings come from ~/.config/eva-desk/settings.lua, generated from eva.toml by `eva-ctl apply`.
-- Nothing here removes your binds: it adds Super+Return (maximise) and re-points the launcher and screenshot keys.

local HOME = os.getenv("HOME")
local ok, S = pcall(dofile, HOME .. "/.config/eva-desk/settings.lua")
if not ok or type(S) ~= "table" then S = {} end
local function opt(key, default)
    local v = S[key]
    if v == nil then return default end
    return v
end
EVA_DESK = true                      -- lets other config files know the theme is active
-- eva-ctl lives in ~/.local/bin after install.sh, or on PATH after a package install (AUR)
local BIN = HOME .. "/.local/bin/"
do
    local f = io.open(BIN .. "eva-ctl")
    if f then f:close() else BIN = "" end
end

---------------------------------------------------------------- border + shadow styles
-- The active theme's colours come from settings.lua (`styles`); these are the wine / bone / gold defaults.
local STYLES = opt("styles", nil) or {
    -- Fight Card: bone border (two close tones drifting slowly, so it reads apart from the shadow
    -- without flickering), hard claret offset shadow
    card = {
        size = 4,
        colors = { "rgb(efe4cf)", "rgb(b9ab92)", "rgb(efe4cf)", "rgb(b9ab92)", "rgb(efe4cf)" },
        shadow = { enabled = true, sharp = true, range = 2, render_power = 1, offset = { 14, 14 },
                   color = "rgb(8e1b33)", color_inactive = "rgba(8e1b3380)" },
    },
    -- Halo: gold and coral with a warm glow (maximised windows, the herald)
    halo = {
        size = 4,
        colors = { "rgb(c9a24a)", "rgb(e86a4a)", "rgb(ffd27a)", "rgb(8e1b33)", "rgb(c9a24a)" },
        shadow = { enabled = true, sharp = false, range = 40, render_power = 2, offset = { 0, 0 },
                   color = "rgba(e86a4a8c)", color_inactive = "rgba(e86a4a30)" },
    },
    -- Iron: slow dark tones with a soft glow
    iron = {
        size = 6,
        colors = { "rgb(3a1a20)", "rgb(8e1b33)", "rgb(1c1012)", "rgb(5c0f22)", "rgb(3a1a20)" },
        shadow = { enabled = true, sharp = false, range = 50, render_power = 2, offset = { 0, 0 },
                   color = "rgba(8e1b3373)", color_inactive = "rgba(8e1b3326)" },
    },
}

local current_style
local function apply_style(name)
    if name == current_style then return end
    current_style = name
    local st = STYLES[name] or STYLES.card
    hl.config({
        general = {
            border_size = st.size,
            col = { active_border = { colors = st.colors, angle = 45 }, inactive_border = opt("inactive_border", "rgba(2a0710aa)") },
        },
        decoration = { shadow = st.shadow },
    })
end

local function style_for(ws)
    if ws then
        if opt("herald", true) and ws.has_fullscreen and ws.fullscreen_mode == 1 then return "halo" end
    end
    return opt("style", "card")
end
local function restyle() apply_style(style_for(hl.get_active_workspace())) end

---------------------------------------------------------------- general look
if opt("gtk_theme", nil) then hl.env("GTK_THEME", opt("gtk_theme", "")) end   -- the theme's GTK skin (gtk/make-gtk-theme.py)
hl.config({
    general = { gaps_in = opt("gaps_in", 4), gaps_out = opt("gaps_out", 8) },
    decoration = { rounding = opt("rounding", 0) },
})
hl.window_rule({ name = "vibe-square-floats", match = { float = true }, rounding = opt("rounding", 0) })
if opt("border_speed", 100) > 0 then
    hl.curve("vibe_linear", { type = "bezier", points = { { 0, 0 }, { 1, 1 } } })
    hl.animation({ leaf = "borderangle", enabled = true, speed = opt("border_speed", 100), bezier = "vibe_linear", style = "loop" })
end
restyle()
hl.on("workspace.active", function(ws) apply_style(style_for(ws)) end)

---------------------------------------------------------------- the stage: room for the figures
-- tiled windows keep to the left so the figure has its part of the screen
-- The rules only match while the workspace is on the main monitor (selector "r[N-N]m[NAME]"): a separate
-- rule from your own `workspace = N, monitor = ...` binding, so toggling the stage never switches that
-- binding off, and the stage gap is never applied to a smaller side monitor.
local stage_rules = {}            -- workspace id -> { rule = WorkspaceRule with the stage gap, figure = bool }

local function main_monitor()
    local wanted, best = opt("main_monitors", {}), nil
    for _, m in ipairs(hl.get_monitors() or {}) do
        for _, w in ipairs(wanted) do
            if m.name == w or (m.description or ""):find(w, 1, true) then return m.name end
        end
        if not best or m.width * m.height > best.width * best.height then best = m end
    end
    if #wanted == 0 and best then return best.name end
    return nil
end

local function stage(ws, px, is_figure, mon)
    if ws and ws > 0 and px and px > 0 and not stage_rules[ws] then
        local g = opt("gaps_out", 8)
        stage_rules[ws] = {
            rule = hl.workspace_rule({ workspace = string.format("r[%d-%d]m[%s]", ws, ws, mon),
                                       gaps_out = { top = g, right = px, bottom = g, left = g } }),
            figure = is_figure,
        }
    end
end

local function build_stages()
    local mon = main_monitor()
    if not mon then return false end           -- monitors not known yet: try again once Hyprland is up
    for _, ws in ipairs(opt("figure_workspaces", {})) do stage(ws, opt("stage_px", 0), true, mon) end
    return true
end
local stages_built = build_stages()

-- the figure on/off switch (eva-ctl figure on|off|toggle); the daemon keeps it in this file
local function figure_saved()
    local f = io.open(HOME .. "/.local/state/eva-desk/figure")
    if not f then return true end
    local s = f:read("*l")
    f:close()
    return s ~= "off"
end
FIGURE_ON = figure_saved()

local function is_maximised(ws) return ws ~= nil and ws.has_fullscreen and ws.fullscreen_mode == 1 end
local function stage_active(entry) return (not entry.figure) or FIGURE_ON end

-- Hyprland sizes a maximised window like a lone tiled one, workspace gaps included, so on a stage
-- workspace it would stop at the stage. Lift the stage while a window there is maximised.
local function sync_stages()
    local maxed = {}
    for _, ws in ipairs(hl.get_workspaces()) do
        if is_maximised(ws) then maxed[ws.id] = true end
    end
    for id, entry in pairs(stage_rules) do
        entry.rule:set_enabled(stage_active(entry) and not maxed[id])
    end
end
sync_stages()
if not stages_built then
    hl.on("hyprland.start", function() if build_stages() then sync_stages() end end)
end

local function toggle_maximise()
    local ws = hl.get_active_workspace()
    local entry = ws and stage_rules[ws.id]
    if entry and stage_active(entry) then
        entry.rule:set_enabled(is_maximised(ws))           -- lift before growing, restore before shrinking
    end
    hl.dispatch(hl.dsp.window.fullscreen({ mode = "maximized" }))
end

---------------------------------------------------------------- side window (figure mode)
-- Super+D puts the focused window into the figure's space as a floating column; he steps aside on that
-- workspace (the daemon sees the "eva-side" tag). Super+D again sends it back to the tiles.
local SIDE_TAG = "eva-side"

local function is_side(w)
    local tags = w and w.tags
    if type(tags) == "string" then return tags:find(SIDE_TAG, 1, true) ~= nil end
    for _, t in ipairs(tags or {}) do
        if t == SIDE_TAG or t == SIDE_TAG .. "*" then return true end
    end
    return false
end

local function reserved_top(mon)
    local r = mon and mon.reserved
    if type(r) == "table" then return r.top or r[2] or 0 end
    return opt("bar_height", 0)
end

local function unside(w)
    hl.dispatch(hl.dsp.focus({ window = "address:" .. w.address }))
    hl.dispatch(hl.dsp.window.tag({ tag = "-" .. SIDE_TAG }))
    if w.floating then hl.dispatch(hl.dsp.window.float({ action = "toggle" })) end
end

local function toggle_side()
    local w = hl.get_active_window()
    if not w then return end
    if is_side(w) then
        unside(w)
        return
    end
    local ws, mon = w.workspace, w.monitor
    local px = opt("stage_px", 0)
    if not FIGURE_ON or not ws or not mon or px <= 0 or not stage_rules[ws.id] then return end
    for _, o in ipairs(hl.get_windows()) do          -- one side window per workspace: swap
        if o.address ~= w.address and o.workspace and o.workspace.id == ws.id and is_side(o) then unside(o) end
    end
    hl.dispatch(hl.dsp.focus({ window = "address:" .. w.address }))
    local g, top = opt("gaps_out", 8), reserved_top(mon)
    local scale = (mon.scale and mon.scale > 0) and mon.scale or 1
    local mw, mh = math.floor(mon.width / scale), math.floor(mon.height / scale)
    if not w.floating then hl.dispatch(hl.dsp.window.float({ action = "toggle" })) end
    hl.dispatch(hl.dsp.window.resize({ x = px - 2 * g, y = mh - top - 2 * g }))
    hl.dispatch(hl.dsp.window.move({ x = mon.x + mw - px + g, y = mon.y + top + g }))
    hl.dispatch(hl.dsp.window.tag({ tag = "+" .. SIDE_TAG }))
end

-- called by the daemon (`hyprctl eval "EVA_SET_FIGURE(true)"`) when the figure is switched on / off
function EVA_SET_FIGURE(on)
    FIGURE_ON = on and true or false
    if not FIGURE_ON then                              -- no figure, no side column: back to the tiles
        local active = hl.get_active_window()
        for _, w in ipairs(hl.get_windows()) do
            if is_side(w) then unside(w) end
        end
        if active then hl.dispatch(hl.dsp.focus({ window = "address:" .. active.address })) end
    end
    sync_stages()
    hl.config({ general = { gaps_out = opt("gaps_out", 8) } })   -- re-tile with the new gaps right away
end

---------------------------------------------------------------- layer surfaces of the daemon
hl.layer_rule({ name = "vibe-instant", match = { namespace = "^eva-(stage|flash|launcher|shot|eyecatch|alarm|alttab|power|pulse|panel-.*)$" }, no_anim = true })

-- a maximised window that closes or leaves maximise any other way puts its stage back
hl.on("window.fullscreen", function() sync_stages(); restyle() end)
hl.on("window.close", function() sync_stages(); restyle() end)

---------------------------------------------------------------- binds
-- maximise ("full space": fills the screen under the bar; true fullscreen stays on its own key)
local max_keys = opt("maximize_binds", nil) or { opt("maximize_bind", "SUPER + RETURN") }
for _, key in ipairs(max_keys) do
    hl.bind(key, toggle_maximise)
end
local launcher_key = opt("launcher_bind", nil)
if launcher_key then
    pcall(hl.unbind, launcher_key)            -- same key, now opens the vibe launcher
    hl.bind(launcher_key, hl.dsp.exec_cmd(BIN .. "eva-ctl launcher"))
end
local shot_key = opt("screenshot_bind", nil)
if shot_key then
    pcall(hl.unbind, shot_key)                -- same key, now the themed screenshot tool
    hl.bind(shot_key, hl.dsp.exec_cmd(BIN .. "eva-ctl shot"))
end
local side_key = opt("side_bind", nil)
if side_key then
    hl.bind(side_key, toggle_side)
end
local alttab_key = opt("alttab_bind", nil)
if alttab_key then
    pcall(hl.unbind, alttab_key)              -- same key, now the cast strip
    hl.bind(alttab_key, hl.dsp.exec_cmd(BIN .. "eva-ctl alttab"))
end
local power_key = opt("power_bind", nil)
if power_key then
    pcall(hl.unbind, power_key)               -- same key, now the Third Impact menu
    hl.bind(power_key, hl.dsp.exec_cmd(BIN .. "eva-ctl power"))
end

---------------------------------------------------------------- autostart
local function start() hl.exec_cmd("pgrep -x eva-desk >/dev/null || " .. BIN .. "eva-desk") end
hl.on("hyprland.start", start)
if not os.getenv("HL_VERIFY") then start() end   -- after a config reload; no-op when already running
