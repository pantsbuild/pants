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

If you see a `create_thrift_libraries` definition, however, chances are good
that there's a `target` definition less deep in the directory structure that
you should target instead. Imagine a project where Thrift definitions are housed
in `myproject/src/main/thrift/com/example/myproject`. In existing projects,
there's a good chance that there's a `BUILD` file in `src/main/thrift`, the
root directory, or elsewhere that has a `target` definition that looks
something like this:

    ::python
    target(name='thrift-scala',
      dependencies=[
        'myproject/src/main/thrift/com/twitter/myproject:thrift-scala'
      ]
    )

This pattern is known as a [[target alias|pants('src/docs/common_tasks:alias')]].  In this case,
you should use the `target` definition:

    :: bash
    $ ./pants gen myproject:thrift-scala # or ./pants compile

Once Scala and/or Java code has been generated, you can find the resulting
classes in `.pants.d/gen/scrooge`. Scala classes will be in the
`scala-finagle` subdirectory while Java classes will be in `java-finagle`;
the classes' namespace will determine the sub-folder from there.  To give an
example, the Scala classes generated in the example above would be located in
`.pants.d/gen/scrooge/scala-finagle/com/example/myproject/thriftscala`.

See Also
--------

- [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]]
