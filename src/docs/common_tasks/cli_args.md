# Pass Command-line Arguments to an Executable

## Problem

You need to run an executable that requires command-line arguments.

## Solution

With Pants, you can pass arguments directly to the process that you're executing by using the special passthrough argument `--`: 

    ::bash
    $ ./pants run myserver:bin -- -log.level='DEBUG'

Everything after the passthrough argument (`--`) will be passed directly as command-line arguments to the executable created by the `myserver:bin` target.

## See Also

* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
