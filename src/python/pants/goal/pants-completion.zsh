# zsh completion support for Pants

function _pants_completions {
    local -a completions
    local current_word

    current_word=${words[$CURRENT]}
    completions=("${(@f)$(pants completion-helper -- "${words[@]}")}")

    _describe 'values' completions
    _files 

    return 0
}

compdef _pants_completions pants
