#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '



# Custom Aliases and Tools
alias update='paru -Syu && flatpak update'
alias hyprupdate='~/hyprdots/update.sh'
alias hyprundo='~/.config/hypr/scripts/undo-update.sh'
eval "$(starship init bash)"
fastfetch
