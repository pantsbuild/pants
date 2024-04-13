#compdef _pants_completions pants

# zsh completion support for Pants
function _pants_completions() {
    local current_word
    current_word=${words[CURRENT]}

    # Check if we're completing a relative (.), absolute (/), or homedir (~) path. If so, fallback to readline (default) completion.
    # This short-circuits the call to the complete goal, which can take a couple hundred milliseconds to complete
    if [[ $current_word =~ "^(\.|/|~\/)" ]]; then
        _files
    else
        # Call the pants complete goal with all of the arguments that we've received so far.
        compadd $(pants complete -- "${words[@]}")
    fi

    return 0
}
