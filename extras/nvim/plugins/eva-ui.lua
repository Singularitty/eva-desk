-- eva-desk look for Neovim (authored in the eva theme; eva-desk-extras rethemes it): NERV status line (title-card blocks + MAGI readouts), title-card buffer tabs,
-- the dashboard as an episode card. Colours follow colors/eva.lua (rethemed by `eva-ctl theme`).
local C = {
  ink = "#0a0612", ink_deep = "#050309", ink3 = "#1b1030", ink4 = "#2a1a48", claret = "#6a2fb8", red = "#a981ff",
  led = "#ff5a1f", coral = "#ff8a45", gold = "#7dff3f", gold_hi = "#c8ff9a", bone = "#ebe6f7", bone2 = "#b7aed0",
  bone3 = "#857b9e", dim = "#5a4b7a",
}

local MODES = {
  n = { "NORMAL", C.bone, C.ink }, no = { "O-PEND", C.bone, C.ink }, nt = { "NORMAL", C.bone, C.ink },
  i = { "INSERT", C.gold, C.ink }, ic = { "INSERT", C.gold, C.ink },
  v = { "VISUAL", C.claret, C.bone }, V = { "V-LINE", C.claret, C.bone }, ["\22"] = { "V-BLOCK", C.claret, C.bone },
  s = { "SELECT", C.claret, C.bone }, S = { "S-LINE", C.claret, C.bone },
  R = { "REPLACE", C.led, C.ink }, Rv = { "V-REPLACE", C.led, C.ink },
  c = { "COMMAND", C.gold_hi, C.ink }, cv = { "EX", C.gold_hi, C.ink },
  t = { "TERM", C.ink3, C.bone2 }, ["!"] = { "SHELL", C.ink3, C.bone2 },
}
local function mode_of() return MODES[vim.fn.mode(1)] or MODES[vim.fn.mode(1):sub(1, 1)] or MODES.n end

---@type LazySpec
return {
  {
    "AstroNvim/astroui",
    ---@type AstroUIOpts
    opts = {
      status = {
        colors = { -- the buffer tabs as title blocks: lilac for the active one, dim labels for the rest
          tabline_bg = C.ink_deep, tabline_fg = C.bone3,
          buffer_active_bg = C.bone, buffer_active_fg = C.ink, buffer_active_path = C.claret,
          buffer_bg = C.ink_deep, buffer_fg = C.bone3, buffer_path = C.dim,
          buffer_visible_bg = C.ink_deep, buffer_visible_fg = C.bone2, buffer_visible_path = C.dim,
          buffer_overflow_bg = C.ink_deep, buffer_overflow_fg = C.dim,
          buffer_close_fg = C.dim, buffer_active_close_fg = C.claret, buffer_visible_close_fg = C.dim,
          tab_active_bg = C.claret, tab_active_fg = C.bone, tab_bg = C.ink_deep, tab_fg = C.bone3, tab_close_fg = C.dim,
          winbar_fg = C.bone2, winbar_bg = C.ink, winbarnc_fg = C.dim, winbarnc_bg = C.ink,
        },
      },
      highlights = {
        init = {
          SnacksDashboardHeader = { fg = C.bone, bold = true },
          SnacksDashboardTitle = { fg = C.red },
          SnacksDashboardKey = { fg = C.claret, bold = true },
          SnacksDashboardDesc = { fg = C.bone, bold = true },
          SnacksDashboardIcon = { fg = C.gold },
          SnacksDashboardFooter = { fg = C.gold },
          SnacksDashboardSpecial = { fg = C.gold },
        },
      },
    },
  },
  {
    "rebelot/heirline.nvim",
    opts = function(_, opts)
      local status = require "astroui.status"
      local hl = function(fg, bg, extra) return vim.tbl_extend("force", { fg = fg, bg = bg }, extra or {}) end
      local block = function(text_fn, bg, fg, extra)
        return { provider = function(self) local t = text_fn(self); return t and t ~= "" and (" " .. t .. " ") or "" end,
                 hl = function() return hl(fg, bg, extra) end }
      end

      local mode = { -- the mode as a title block
        provider = function() return " " .. mode_of()[1] .. " " end,
        hl = function() local m = mode_of(); return { fg = m[3], bg = m[2], bold = true } end,
        update = { "ModeChanged", pattern = "*:*" },
      }
      local file = { -- the file in a purple block, the dot marks a modified buffer
        provider = function()
          local name = vim.fn.expand "%:t"
          if name == "" then name = "[no name]" end
          local mark = vim.bo.modified and " ●" or (vim.bo.readonly and " 󰌾" or "")
          return " " .. name .. mark .. " "
        end,
        hl = function() return hl(vim.bo.modified and C.gold_hi or C.bone, C.claret, { bold = true }) end,
        update = { "BufEnter", "BufModifiedSet", "BufWritePost" },
      }
      local sync = { -- git as the SYNC readout
        condition = function() return vim.b.gitsigns_head ~= nil end,
        {
          provider = function() return " SYNC" end, hl = hl(C.gold, "NONE"),
        },
        { provider = "·", hl = hl(C.dim, "NONE") },
        { provider = function() return vim.b.gitsigns_head end, hl = hl(C.gold, "NONE", { bold = true }) },
        {
          provider = function()
            local s = vim.b.gitsigns_status_dict or {}
            local parts = {}
            if (s.added or 0) > 0 then parts[#parts + 1] = "+" .. s.added end
            if (s.changed or 0) > 0 then parts[#parts + 1] = "!" .. s.changed end
            if (s.removed or 0) > 0 then parts[#parts + 1] = "✘" .. s.removed end
            return #parts > 0 and (" " .. table.concat(parts, " ")) or ""
          end,
          hl = hl(C.coral, "NONE"),
        },
        { provider = " " },
      }
      local diag = { -- MAGI counts: E W H
        condition = function() return #vim.diagnostic.get(0) > 0 end,
        update = { "DiagnosticChanged", "BufEnter" },
        {
          provider = function()
            local e = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.ERROR })
            return e > 0 and (" E " .. e) or ""
          end, hl = hl(C.led, "NONE", { bold = true }),
        },
        {
          provider = function()
            local w = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.WARN })
            return w > 0 and (" W " .. w) or ""
          end, hl = hl(C.coral, "NONE"),
        },
        {
          provider = function()
            local h = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.HINT })
              + #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.INFO })
            return h > 0 and (" H " .. h) or ""
          end, hl = hl(C.bone3, "NONE"),
        },
        { provider = " " },
      }
      local lsp = block(function()
        local names = {}
        for _, c in ipairs(vim.lsp.get_clients { bufnr = 0 }) do names[#names + 1] = c.name:upper() end
        return #names > 0 and table.concat(names, " · ") or nil
      end, "NONE", C.bone3)
      local ftype = block(function()
        local ft = vim.bo.filetype ~= "" and vim.bo.filetype:upper() or nil
        local enc = (vim.bo.fileencoding ~= "" and vim.bo.fileencoding or vim.o.encoding):upper()
        return ft and (ft .. " · " .. enc) or enc
      end, "NONE", C.bone2)
      local nav = { provider = " LN %l · COL %02c ", hl = hl(C.bone, C.ink3) }
      local pct = { provider = " %p%% ", hl = hl(C.ink, C.bone, { bold = true }) }

      opts.statusline = {
        hl = { fg = C.bone, bg = "NONE" },
        mode, file, sync, diag,
        status.component.fill(),
        status.component.cmd_info(),
        status.component.fill(),
        lsp, ftype, nav, pct,
      }
      return opts
    end,
  },
  {
    "folke/snacks.nvim",
    opts = function(_, opts)
      opts.dashboard = opts.dashboard or {}
      opts.dashboard.preset = vim.tbl_extend("force", opts.dashboard.preset or {}, {
        header = table.concat({
          "███╗   ██╗███████╗██████╗ ██╗   ██╗",
          "████╗  ██║██╔════╝██╔══██╗██║   ██║",
          "██╔██╗ ██║█████╗  ██████╔╝██║   ██║",
          "██║╚██╗██║██╔══╝  ██╔══██╗╚██╗ ██╔╝",
          "██║ ╚████║███████╗██║  ██║ ╚████╔╝ ",
          "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ",
        }, "\n"),
        keys = {
          { key = "f", action = "<Leader>ff", icon = "01", desc = "FIND FILE" },
          { key = "o", action = "<Leader>fo", icon = "02", desc = "RECENT" },
          { key = "w", action = "<Leader>fw", icon = "03", desc = "GREP" },
          { key = "n", action = "<Leader>n", icon = "04", desc = "NEW FILE" },
          { key = "s", action = "<Leader>Sl", icon = "05", desc = "LAST SESSION" },
          { key = "q", action = ":qa", icon = "06", desc = "QUIT" },
        },
      })
      opts.dashboard.sections = {
        { text = { { "EPISODE 00 · NEOVIM", hl = "SnacksDashboardTitle" } }, align = "center", padding = 1 },
        { section = "header", padding = 1 },
        { text = { { " 起動 · 編集 ", hl = "SnacksDashboardDesc" } }, align = "center", padding = 2 },
        { section = "keys", gap = 1, padding = 2 },
        { section = "startup", icon = "MAGI ·" },
      }
      return opts
    end,
  },
}
