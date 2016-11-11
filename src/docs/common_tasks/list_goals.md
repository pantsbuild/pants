# List All Pants Goals

## Problem

You want to find out which goals are supported by your version of Pants.

## Solution

Invoke the `goals` goal:

    :::bash
    $ ./pants goals

The resulting list should look something like this:

    :::
    Installed goals:
                   autoblame: Finds the responsible individuals, group, JIRA project and BUILD file for a given target,
                   bash-completion: Generate a Bash shell script that teaches Bash how to autocomplete pants command lines.
                   bench: Run benchmarks.
                   binary: Create a runnable binary.
                   # etc.

You can get help output for each Pants goal (including all the available flags for that goal) by appending the `-h` or `--help` flags or the `help` command. Here are three equivalent examples:

    :::bash
    $ ./pants goals -h
    $ ./pants goals --help
    $ ./pants goals help

## See Also

* [[List Available Targets|pants('src/docs/common_tasks:list_targets')]]
