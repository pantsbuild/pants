# Define a Scala or Java Library Target

## Problem

You need to define a new Scala or Java **library target** that other projects can use as a dependency.

**Note**: If you need to define a new Scala or Java *binary target*, see [[Define a JVM Executable|pants('src/docs/common_tasks:jvm_binary')]]

## Solution

Add a `scala_library` or `java_library` target to a `BUILD` file in the appropriate directory. A `scala_library` or `java_library` target will enable you to compile the library using Pants' `compile` goal. Here's an example:

    ::bash
    $ ./pants compile src/scala/com/myorg/myproject/example:hello

## Discussion

A `scala_library` or `java_library` target should specify the following:

* A `name` for the library. This may be something like just `scala` if you have only one `scala_library` target in a project or something more specific like `client-lib`.
* Either the `source` field with a single file or the `sources` field with a list of file names and globs.
* A list of `dependencies` (optional). More info on dependencies can be found in [[Add a Dependency on Another Target|pants('src/docs/common_tasks:dependencies')]].

Here's an example target definition:

    ::python
    # src/scala/com/myorg/myproject/example/BUILD
    scala_library(
      name='scala',
      sources=['*.scala'],
      dependencies=[
        'src/scala/com/myorg/myproject/client-lib',
        'src/scala/com/myorg/myproject/analytics-lib',
        'static/resources/json:config',
      ],
    )

That library can then be compiled with:

    ::python
    $ ./pants compile src/scala/com/myorg/myproject/example

You can combine library targets together into a single target using a **target aggregate**. More info can be found in [[Create a Target Aggregate|pants('src/docs/common_tasks:target_aggregate')]].

## See Also

* [[Compile a Library Target|pants('src/docs/common_tasks:compile')]]
* [[Define a JVM Executable|pants('src/docs/common_tasks:jvm_binary')]]
* [[Create a Bundled zip or Other Archive|pants('src/docs/common_tasks:bundle')]]
* [[Create a Target Aggregate|pants('src/docs/common_tasks:target_aggregate')]]
