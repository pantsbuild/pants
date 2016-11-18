# Access a REPL for a Target

## Problem

You're working on a Scala or Python project and would like to interact with a library target through a read-eval-print loop (REPL).

## Solution

The pants `repl` goal will open up an interactive Scala or Python REPL session for a library target.

    ::bash
    $ ./pants repl myproject/src/main/scala

## Discussion

When using the `repl` goal, you need to target a `BUILD` file containing either a `scala_library` or `python_library` target. The REPL that you open up via Pants is just a normal Scala or Python REPL with all of the functionality that you're used to if you're familiar with those languages. When using the Scala REPL, Pants will compile the specified dependencies along with your code and load the resulting classes into your classpath.

If you're working on a Scala project that has, for example, `com.twitter.util.Future` listed as a dependency, you can load that dependency into the REPL like you usually would:

    ::scala
    scala> import com.twitter.util.Future
    import com.twitter.util.Future

**Note**: When opening up a REPL via Pants, only those dependencies that are available to the chosen target can be imported (meaning that the dependencies specified in the `scala_library` or `python_library` definition). If there's a dependency that you'd like to use only in the REPL, you will need to create a library target that includes that dependency.

It's also possible to open the Scala REPL without first compiling the specified library using the `repl-dirty` goal:

    ::bash
    $ ./pants repl-dirty myproject/src/main/scala

## See Also

* [[Define a Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]]
* [[Define a Python Library Target|pants('src/docs/common_tasks:python_library')]]
