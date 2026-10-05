# eva-desk colours for the shell (loaded at the end of ~/.zshrc)

# autosuggestions: dim grey ghost text
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=#5a4b7a'

# syntax highlighting
typeset -gA ZSH_HIGHLIGHT_STYLES
ZSH_HIGHLIGHT_STYLES[default]='fg=#ebe6f7'
ZSH_HIGHLIGHT_STYLES[unknown-token]='fg=#ff5a1f'
ZSH_HIGHLIGHT_STYLES[command]='fg=#ebe6f7'
ZSH_HIGHLIGHT_STYLES[builtin]='fg=#ebe6f7'
ZSH_HIGHLIGHT_STYLES[alias]='fg=#ebe6f7'
ZSH_HIGHLIGHT_STYLES[function]='fg=#ebe6f7'
ZSH_HIGHLIGHT_STYLES[precommand]='fg=#c8ff9a,italic'
ZSH_HIGHLIGHT_STYLES[reserved-word]='fg=#dcaaff'
ZSH_HIGHLIGHT_STYLES[commandseparator]='fg=#ff8a45'
ZSH_HIGHLIGHT_STYLES[path]='fg=#ebe6f7,underline'
ZSH_HIGHLIGHT_STYLES[globbing]='fg=#adb3ff'
ZSH_HIGHLIGHT_STYLES[single-hyphen-option]='fg=#7dff3f'
ZSH_HIGHLIGHT_STYLES[double-hyphen-option]='fg=#7dff3f'
ZSH_HIGHLIGHT_STYLES[single-quoted-argument]='fg=#c8ff9a'
ZSH_HIGHLIGHT_STYLES[double-quoted-argument]='fg=#c8ff9a'
ZSH_HIGHLIGHT_STYLES[dollar-quoted-argument]='fg=#c8ff9a'
ZSH_HIGHLIGHT_STYLES[back-quoted-argument]='fg=#dcaaff'
ZSH_HIGHLIGHT_STYLES[dollar-double-quoted-argument]='fg=#adb3ff'
ZSH_HIGHLIGHT_STYLES[redirection]='fg=#ff8a45'
ZSH_HIGHLIGHT_STYLES[comment]='fg=#5a4b7a,italic'
ZSH_HIGHLIGHT_STYLES[arg0]='fg=#ebe6f7'

# file colours (the eva vivid theme)
command -v vivid >/dev/null && export LS_COLORS="$(vivid generate eva)"

# completion menu in matching colours
zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
zstyle ':completion:*' menu select

# prompt
command -v starship >/dev/null && eval "$(starship init zsh)"
