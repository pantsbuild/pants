# Generate Code from Thrift Definitions

## Problem

You've created Thrift definitions (structs, services, etc.) and you need to generated either Thrift-based

* **classes** for use within your Scala or Java project, or
* **libraries** that can be used by your project or other projects.

## Solution

Use the `gen` goal to generate code from Thrift definitions. Here's an example:

    ::bash
    $ ./pants gen myproject/src/thrift:thrift-scala

If you need to compile a Scala or Java [[library target|pants('src/docs/common_tasks:jvm_library')]] instead, use the `compile` goal instead.

## Discussion

There are two types of Thrift target definitions that you will find in `BUILD` files in existing projects:

* `java_thrift_library` (for Scala and Java) and `python_thrift_library`
* `create_thrift_libraries`

You can use the `gen` and `compile` goals directly with `java_thrift_library` targets. Thus, you could target a `BUILD` file containing this definition...

    ::python
    java_thrift_library(name='thrift-java',
      # Other parameters
    )

...like this using Pants:

    ::bash
    $ ./pants gen myproject/src/main/thrift:thrift-java

`create_thrift_libraries` targets work somewhat differently, however.
