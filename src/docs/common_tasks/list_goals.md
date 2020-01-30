# List All Pants Goals

## Problem

You want to find out which goals are supported by your version of Pants.

## Solution

Invoke the `goals` goal:

    :::bash
    $ ./pants goals

The resulting list should look something like this:

    :::
    Use `./pants help $goal` to get help for a particular goal.

        bash-completion: Generate a Bash shell script that teaches Bash how to autocomplete pants command lines.
                  bench: Run benchmarks.
                 binary: Create a runnable binary.
              bootstrap: Bootstrap tools needed by subsequent build steps.
                   # etc.

You can get help output for each Pants goal (including all the available flags for that goal) by appending the `-h` or `--help` flags or the `help` command. Here are three equivalent examples:

    :::bash
    $ ./pants test -h
    $ ./pants test --help
    $ ./pants help test

## See Also

* [[List Available Targets|pants('src/docs/common_tasks:list_targets')]]
