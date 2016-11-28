# Compile a JVM Target

## Problem

You need to compile a JVM binary or library target that you're working on, e.g. to ensure that the target compiles successfully.

## Solution

The `compile` goal enables you to compile Scala or Java [[binaries|]] and libraries. Here's an example:

    :::bash
    $ ./pants compile examples/src/scala/org/pantsbuild/hello/exe:exe


The `compile` goal requires you to target a `BUILD` file containing either a `java_library`, `scala_library`, `java_binary` or `scala_binary` target. For the CLI example above, the target `BUILD` file might look something like this:

    :::python
    jvm_binary(
      dependencies=[
        'examples/src/scala/org/pantsbuild/example/hello/welcome:welcome',
      ],
      source='Exe.scala',
      main='org.pantsbuild.example.hello.exe.Exe',
    )


## Discussion

This works somewhat differently if you're working on Python projects. Because Python doesn't require compilation, `python_library` targets do not need a separate compilation phase. You can, however, compile Python CLI apps into PEX files, using a `python_binary` target. See [[Build a Python Executable|pants('src/docs/common_tasks:pex')]] and [[Run a Binary Target|pants('src/docs/common_tasks:run')]] for more info.
