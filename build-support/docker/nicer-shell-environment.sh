#!/bin/bash

if [[ -f ~/.bashrc ]]; then
  source ~/.bashrc
fi

# long mode, show all, natural sort, type squiggles, friendly sizes
if hash dircolors 2>/dev/null && [[ ! "$TERM" =~ 'dumb|emacs' ]]; then
  eval "$(dircolors -b)"
  # -A, --almost-all           do not list implied . and ..
  # -F, --classify             append indicator (one of */=>@|) to entries
  # -l                         use a long listing format
  # -h, --human-readable       with -l and -s, print sizes like 1K 234M 2G etc.
  #     --si                   likewise, but use powers of 1000 not 1024
  # -v                         natural sort of (version) numbers within text
  LSOPTS='-lAvFh --si --color=always'
  LLOPTS='-lAvFh --color=always'
else
  export CLICOLOR=YES
  LSOPTS='-lAvFh'
  LLOPTS=''
fi

alias ls="ls $LSOPTS"
alias ll="ls $LLOPTS | less -FX"

export PAGER=less
# Never wrap long lines by default
# I'd love to have the effect of -F, but I don't want -X all the time, alas.
export LESS="-RMi~Kq"

export PS1='\u@\H:\w (bash \V)$ '
