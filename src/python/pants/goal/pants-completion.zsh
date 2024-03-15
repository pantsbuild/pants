#compdef _pants_completions pants

# zsh completion support for Pants
function _pants_completions() {
  compadd $(pants complete -- "${words[@]}")
}
