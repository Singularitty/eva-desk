-- vibe (eva): ink / lilac / Unit-01 purple / acid green, the same palette as the desktop; keywords purple, errors NERV orange.
vim.cmd.highlight("clear")
if vim.fn.exists("syntax_on") == 1 then vim.cmd.syntax("reset") end
vim.g.colors_name = "vibe"
vim.o.termguicolors = true
vim.o.background = "dark"

local c = {
  ink = "#0a0612", ink_deep = "#050309", ink2 = "#130b20", ink3 = "#1b1030", ink4 = "#2a1a48", ink5 = "#44307a",
  wine = "#2b1450", claret = "#6a2fb8", claret_hi = "#8d4ff0", red = "#a981ff", led = "#ff5a1f", coral = "#ff8a45",
  gold = "#7dff3f", gold_hi = "#c8ff9a", bone = "#ebe6f7", bone2 = "#b7aed0", bone3 = "#857b9e", dim = "#5a4b7a",
  green = "#6fd63a", green_hi = "#9dff5a", blue = "#8a8fe8", blue_hi = "#adb3ff", rose = "#c77dff", rose_hi = "#dcaaff",
  teal = "#6fbf9f",
}

local function hi(group, spec) vim.api.nvim_set_hl(0, group, spec) end
local function link(group, to) vim.api.nvim_set_hl(0, group, { link = to }) end

-- editor
hi("Normal", { fg = c.bone, bg = c.ink })
hi("NormalNC", { fg = c.bone, bg = c.ink })
hi("NormalFloat", { fg = c.bone, bg = c.ink })
hi("FloatBorder", { fg = c.bone, bg = c.ink })
hi("FloatTitle", { fg = c.ink, bg = c.bone, bold = true })
hi("Cursor", { fg = c.ink, bg = c.bone })
link("lCursor", "Cursor"); link("CursorIM", "Cursor"); link("TermCursor", "Cursor")
hi("CursorLine", { bg = c.ink2 })
hi("CursorColumn", { bg = c.ink2 })
hi("ColorColumn", { bg = c.ink2 })
hi("CursorLineNr", { fg = c.gold, bold = true })
hi("LineNr", { fg = c.dim })
hi("LineNrAbove", { fg = c.dim }); hi("LineNrBelow", { fg = c.dim })
hi("SignColumn", { fg = c.dim })
hi("FoldColumn", { fg = c.dim })
hi("Folded", { fg = c.bone3, bg = c.ink2 })
hi("EndOfBuffer", { fg = c.ink4 })
hi("NonText", { fg = c.ink5 })
hi("Whitespace", { fg = c.ink4 })
hi("SpecialKey", { fg = c.ink5 })
hi("Conceal", { fg = c.bone3 })
hi("Visual", { bg = c.wine })
hi("VisualNOS", { bg = c.wine })
hi("Search", { fg = c.ink, bg = c.gold })
hi("CurSearch", { fg = c.ink, bg = c.bone, bold = true })
hi("IncSearch", { fg = c.ink, bg = c.bone, bold = true })
hi("Substitute", { fg = c.ink, bg = c.red })
hi("MatchParen", { fg = c.gold_hi, bg = c.claret, bold = true })
hi("WinSeparator", { fg = c.ink5 })
link("VertSplit", "WinSeparator")
hi("Directory", { fg = c.blue })
hi("Title", { fg = c.bone, bold = true })
hi("Question", { fg = c.gold })
hi("MoreMsg", { fg = c.green })
hi("ModeMsg", { fg = c.bone, bold = true })
hi("WarningMsg", { fg = c.gold })
hi("ErrorMsg", { fg = c.led, bold = true })
hi("WildMenu", { fg = c.ink, bg = c.bone })
hi("QuickFixLine", { bg = c.wine, bold = true })
hi("Underlined", { underline = true })
hi("Ignore", { fg = c.dim })
hi("Error", { fg = c.led })
hi("Todo", { fg = c.ink, bg = c.gold, bold = true })

-- statusline / tabline / winbar
hi("StatusLine", { fg = c.bone, bg = c.ink4 })
hi("StatusLineNC", { fg = c.bone3, bg = c.ink2 })
hi("TabLine", { fg = c.bone2, bg = c.ink4 })
hi("TabLineFill", { bg = c.ink })
hi("TabLineSel", { fg = c.ink, bg = c.bone, bold = true })
hi("WinBar", { fg = c.bone2 }); hi("WinBarNC", { fg = c.bone3 })

-- menus
hi("Pmenu", { fg = c.bone, bg = c.ink })
hi("PmenuSel", { fg = c.ink, bg = c.bone, bold = true })
hi("PmenuSbar", { bg = c.ink3 })
hi("PmenuThumb", { bg = c.claret })
hi("PmenuKind", { fg = c.gold }); hi("PmenuExtra", { fg = c.bone3 })

-- diff
hi("DiffAdd", { bg = "#143a16" }); hi("DiffChange", { bg = "#2b1a4a" })
hi("DiffDelete", { fg = c.claret, bg = "#1c0d36" }); hi("DiffText", { bg = "#4a3080" })
hi("Added", { fg = c.green }); hi("Changed", { fg = c.gold }); hi("Removed", { fg = c.led })

-- spell
hi("SpellBad", { undercurl = true, sp = c.led }); hi("SpellCap", { undercurl = true, sp = c.gold })
hi("SpellLocal", { undercurl = true, sp = c.blue }); hi("SpellRare", { undercurl = true, sp = c.rose })

-- syntax: bone text, red keywords, gold functions, muted accents
hi("Comment", { fg = c.bone3, italic = true })
hi("Constant", { fg = c.coral })
hi("String", { fg = c.green_hi })
hi("Character", { fg = c.green_hi })
hi("Number", { fg = c.gold_hi }); hi("Boolean", { fg = c.coral }); hi("Float", { fg = c.gold_hi })
hi("Identifier", { fg = c.bone })
hi("Function", { fg = c.gold, bold = true })
hi("Statement", { fg = c.red }); hi("Conditional", { fg = c.red }); hi("Repeat", { fg = c.red })
hi("Label", { fg = c.red }); hi("Operator", { fg = c.bone2 }); hi("Keyword", { fg = c.red, italic = true })
hi("Exception", { fg = c.led })
hi("PreProc", { fg = c.rose_hi }); hi("Include", { fg = c.rose_hi }); hi("Define", { fg = c.rose_hi })
hi("Macro", { fg = c.rose_hi }); hi("PreCondit", { fg = c.rose_hi })
hi("Type", { fg = c.blue_hi }); hi("StorageClass", { fg = c.red }); hi("Structure", { fg = c.blue_hi })
hi("Typedef", { fg = c.blue_hi })
hi("Special", { fg = c.coral }); hi("SpecialChar", { fg = c.coral }); hi("Tag", { fg = c.gold })
hi("Delimiter", { fg = c.bone2 }); hi("SpecialComment", { fg = c.bone3, italic = true })
hi("Debug", { fg = c.led })

-- treesitter
local ts = {
  ["@variable"] = { fg = c.bone }, ["@variable.builtin"] = { fg = c.rose_hi }, ["@variable.parameter"] = { fg = c.bone2, italic = true },
  ["@variable.member"] = { fg = c.blue_hi }, ["@property"] = { fg = c.blue_hi }, ["@field"] = { fg = c.blue_hi },
  ["@constant"] = { fg = c.coral }, ["@constant.builtin"] = { fg = c.coral, bold = true },
  ["@module"] = { fg = c.bone2 }, ["@string.escape"] = { fg = c.coral }, ["@string.regexp"] = { fg = c.teal },
  ["@function"] = { fg = c.gold, bold = true }, ["@function.call"] = { fg = c.gold }, ["@function.builtin"] = { fg = c.gold_hi },
  ["@function.method"] = { fg = c.gold, bold = true }, ["@function.method.call"] = { fg = c.gold },
  ["@constructor"] = { fg = c.blue_hi }, ["@type"] = { fg = c.blue_hi }, ["@type.builtin"] = { fg = c.blue },
  ["@keyword"] = { fg = c.red, italic = true }, ["@keyword.function"] = { fg = c.red, italic = true },
  ["@keyword.return"] = { fg = c.led, italic = true }, ["@keyword.operator"] = { fg = c.red },
  ["@operator"] = { fg = c.bone2 }, ["@punctuation"] = { fg = c.bone2 }, ["@punctuation.special"] = { fg = c.coral },
  ["@tag"] = { fg = c.red }, ["@tag.attribute"] = { fg = c.gold_hi }, ["@tag.delimiter"] = { fg = c.bone3 },
  ["@attribute"] = { fg = c.rose_hi }, ["@comment"] = { fg = c.bone3, italic = true },
  ["@markup.heading"] = { fg = c.red, bold = true }, ["@markup.strong"] = { bold = true },
  ["@markup.italic"] = { italic = true }, ["@markup.link"] = { fg = c.blue, underline = true },
  ["@markup.raw"] = { fg = c.green_hi }, ["@markup.list"] = { fg = c.gold },
}
for g, s in pairs(ts) do hi(g, s) end
hi("@lsp.type.comment", {})

-- diagnostics
for name, col in pairs { Error = c.led, Warn = c.gold, Info = c.blue, Hint = c.teal, Ok = c.green } do
  hi("Diagnostic" .. name, { fg = col })
  hi("DiagnosticVirtualText" .. name, { fg = col, bg = c.ink2 })
  hi("DiagnosticUnderline" .. name, { undercurl = true, sp = col })
  hi("DiagnosticSign" .. name, { fg = col })
end

-- git signs / plugins
hi("GitSignsAdd", { fg = c.green }); hi("GitSignsChange", { fg = c.gold }); hi("GitSignsDelete", { fg = c.red })
hi("BlinkCmpMenu", { link = "Pmenu" }); hi("BlinkCmpMenuBorder", { link = "FloatBorder" })
hi("BlinkCmpMenuSelection", { link = "PmenuSel" }); hi("BlinkCmpDoc", { link = "NormalFloat" })
hi("BlinkCmpDocBorder", { link = "FloatBorder" }); hi("BlinkCmpLabelMatch", { fg = c.gold, bold = true })
hi("TelescopeSelection", { fg = c.ink, bg = c.bone, bold = true }); hi("TelescopeMatching", { fg = c.gold, bold = true })
hi("TelescopeTitle", { fg = c.ink, bg = c.bone, bold = true }); hi("TelescopePromptPrefix", { fg = c.red })
hi("NeoTreeDirectoryName", { fg = c.bone }); hi("NeoTreeDirectoryIcon", { fg = c.gold })
hi("NeoTreeRootName", { fg = c.red, bold = true }); hi("NeoTreeGitModified", { fg = c.gold })
hi("NeoTreeGitAdded", { fg = c.green }); hi("NeoTreeGitUntracked", { fg = c.rose_hi })
hi("WhichKey", { fg = c.gold }); hi("WhichKeyGroup", { fg = c.red }); hi("WhichKeyDesc", { fg = c.bone })
hi("SnacksDashboardHeader", { fg = c.red }); hi("SnacksDashboardIcon", { fg = c.gold })
hi("SnacksDashboardKey", { fg = c.gold_hi }); hi("SnacksDashboardDesc", { fg = c.bone })
hi("SnacksPickerTitle", { fg = c.ink, bg = c.bone, bold = true })
hi("IndentBlanklineChar", { fg = c.ink4 }); hi("SnacksIndent", { fg = c.ink4 }); hi("SnacksIndentScope", { fg = c.claret })
hi("RenderMarkdownCode", { bg = c.ink2 })

-- terminal palette for :terminal (same as kitty)
local term = { c.ink4, c.claret_hi, c.green, c.gold, c.blue, c.rose, c.teal, c.bone2,
               c.dim, c.red, c.green_hi, c.gold_hi, c.blue_hi, c.rose_hi, "#9ad9c0", c.bone }
for i, col in ipairs(term) do vim.g["terminal_color_" .. (i - 1)] = col end
