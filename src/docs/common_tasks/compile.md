# Compile a Library Target

## Problem

You need to compile a library or binary target that you're currently working on, either so that you can use it outside of your project or because you want to make sure that it will compile successfully.

## Solution

The `compile` goal enables you to compile Scala or Java binaries. Here's an example:

    :::bash
    $ ./pants compile myproject/src/main/scala/com/square/myproject:scala

This work somewhat differently if you're working on `python_library` targets because these targets never require a separate compilation phase, even when you're using the library locally. You can, however, compile Python binary targets. See **Specify a Python Executable** and **Run a Binary Target** for more info.

## Discussion

The `compile` goal requires you to target a `BUILD` file containing either a `scala_library` or `java_library` target. For the CLI example in the [Solution](#Solution) section above, the target `BUILD` file might look something like this:

    :::python
    scala_library(name='scala',
      sources=rglobs('\*.scala'),
      dependencies=[
        '3rdparty/jvm/com/twitter/finagle'
      ]
    )
