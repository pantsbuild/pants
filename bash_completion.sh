function _pants_completions()
{
    local current_word
    current_word=${COMP_WORDS[COMP_CWORD]}

    # Call the completion-helper with all of the arguments that we've received so far.
    COMPREPLY=( $(pants completion-helper -- "${COMP_WORDS[@]}") )

    return 0
}

### TODO: Remove these two autoloads
autoload -U +X bashcompinit && bashcompinit
autoload -Uz compinit && compinit
###

complete -F _pants_completions pants
