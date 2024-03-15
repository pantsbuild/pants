# bash completion support for Pants

function _pants_completions() {
    local current_word
    current_word=${COMP_WORDS[COMP_CWORD]}

    # Check if we're completing a relative (.), absolute (/), or homedir (~) path. If so, fallback to readline (default) completion.
    # This short-circuits the call to the complete goal, which can take a couple hundred milliseconds to complete
    if [[ $current_word =~ "^(\.|/|~\/)" ]]; then
        COMPREPLY=()
    else 
        # Call the pants complete goal with all of the arguments that we've received so far.
        COMPREPLY=( $(pants complete -- "${COMP_WORDS[@]}") )
    fi

    return 0
}

complete -o default -F _pants_completions pants
