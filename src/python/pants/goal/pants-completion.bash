# bash completion support for Pants

function _pants_completions()
{
    local current_word
    current_word=${COMP_WORDS[COMP_CWORD]}

    # Call the complete goal with all of the arguments that we've received so far.
    COMPREPLY=( $(pants complete -- "${COMP_WORDS[@]}") )

    # If pants complete doesn't provide any completions, fall back to file system completions.
    if [ ${#COMPREPLY[@]} -eq 0 ]; then
        COMPREPLY=( $(compgen -f -- "$current_word") )
    fi

    return 0
}

complete -F _pants_completions pants
