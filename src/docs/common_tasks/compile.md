# Compile a JVM Target

## Problem

You need to compile a library target that you're currently working on, e.g. if you want to ensure that the target will compile successfully.

## Solution

The `compile` goal enables you to compile Scala or Java [[binaries|]]. Here's an example:

    :::bash
    $ ./pants compile myproject/src/main/scala/com/square/myproject:scala

This work somewhat differently if you're working on `python_library` targets because these targets never require a separate compilation phase, even when you're using the library locally. You can, however, compile Python binary targets. See [[Build a Python Executable|pants('src/docs/common_tasks:pex')]] and [[Run a Binary Target|pants('src/docs/common_tasks:run')]]. for more info.

## Discussion

The `compile` goal requires you to target a `BUILD` file containing either a `scala_library` or `java_library` target. For the CLI example in the [Solution](#Solution) section above, the target `BUILD` file might look something like this:

    :::python
    scala_library(name='scala',
      sources=rglobs('*.scala'),
      dependencies=[
        '3rdparty/jvm/com/twitter/finagle'
      ]
    )
