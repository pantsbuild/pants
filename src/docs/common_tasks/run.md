# Run a Binary Target

## Problem

Your project is a Thrift server, command-line tool, or other **binary target** that you want to execute.

## Solution

The `run` goal enables you to run Scala, Java, or Python executables. Here's an example:

    :::bash
    $ ./pants run myproject:bin

If you need to pass in command-line arguments when running an executable, see **Pass Command-line Arguments to an Executable**. If you're working on a Scala or Java project and need to pass in JVM options, see **Specify JVM Options**.

## Discussion

### Scala and Java

The `run` goal will both compile *and* execute a binary target. For Scala and Java projects, you can run any target with a `jvm_binary` definition. Here's an example of a `BUILD` file that would enable you to run a Scala or Java target:

    :::python
    jvm_binary(name='bin',
      basename='my-executable',
      ...
    )

You can also run a Scala or Java binary target without compiling it first, using the `run-dirty` goal:

    :::bash
    $ ./pants run-dirty myproject/src/main/scala:bin

### Python

For Python projects, executables are specified using a `python_binary` definition. Here's an example:

    :::python
    python_binary(name='bin',
      basename='my-executable',
      ...
    )

## See Also

* [[Compile a Library Target|pants('src/docs/common_tasks:compile')]]
* **Define a JVM Executable**
* **Specify a Python Executable (PEX)**
* **Pass Command-line Arguments to an Executable**
* **Specify JVM Options**
