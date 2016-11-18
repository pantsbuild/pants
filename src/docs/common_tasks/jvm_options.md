# Specify JVM Options

## Problem

You need to specify command-line options for the JVM when running a Scala or Java goal, e.g. to set GC options, memory limits, enable debugging, etc.

Examples of JVM options can be found [here](https://docs.oracle.com/cd/E13150_01/jrockit_jvm/jrockit/jrdocs/refman/optionX.html).

## Solution

Use the `--jvm-run-jvm-options` flag to pass the options. Here's an example:

    ::bash
    $ ./pants run my-jvm-project:bin --jvm-run-jvm-options='-XX:+UseParallelGC,-Xdebug,-Xprof'

As you can see in the example above, you can pass in multiple options separated by a comma. Multiple options can also be separated by line (just make sure not to use commas):

    ::bash
    $ ./pants run my-jvm-project:bin --jvm-run-jvm-options="
      -XX:+UseParallelGC
      -Xdebug
      -Xprof
      "


## Discussion

The pants argument `--jvm-run-jvm-options` is *only* used for arguments passed to the JVM itself, not to the executable target. If you need to pass command-line arguments to the executable target, see [[Pass Command-line Arguments to an Executable|pants('src/docs/common_tasks:cli_args')]].


## See Also

* [[Pass Command-line Arguments to an Executable|pants('src/docs/common_tasks:cli_args')]]
* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
