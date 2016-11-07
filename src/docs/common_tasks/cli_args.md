# Pass Command-line Arguments to an Executable

## Problem

You need to run an executable that requires command-line arguments.

## Solution

With Pants, you can use passthrough to pass arguments directly to the process that you're executing:

    ::bash
    $ ./pants run myserver:bin -- -log.level='DEBUG'

## See Also

* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
