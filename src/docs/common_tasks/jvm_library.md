# Define a Scala or Java Library Target

## Problem

You need to define a new Scala or Java **library target** that other projects can use as a dependency.

**Note**: If you need to define a new Scala or Java *binary target*, see [[Define a JVM Executable|pants('src/docs/common_tasks:jvm_binary')]]

## Solution

Add a `scala_library` or `java_library` target to a `BUILD` file in the appropriate directory. A `scala_library` or `java_library` target will enable you to compile the library using Pants' `compile` goal. Here's an example:

    ::bash
    $ ./pants compile myproject/src/main/scala
    # Assuming there's a BUILD file with a scala_library definition named "scala" in that location

## Discussion

A `scala_library` or `java_library` target should specify the following:

* A `name` for the library. This may be something like just `scala` if you have only one `scala_library` target in a project or something more specific like `client-lib`.
* Either a single `source` file or a list of `sources`. If you're including just a few files, you should consider specifying a sources list, e.g. `sources=['File1.scala', 'File2.scala']`; if you're including, you may want to specify a `globs` or `rglobs`, e.g. `sources=globs('*.scala')`. More info can be found in [[Use globs and rglobs to Group Files|pants('src/docs/common_tasks:globs')]]. The example further down use an `rglobs` definition.
* A list of `dependencies` (optional). More info on dependencies can be found in [[Add a Dependency on Another Target|pants('src/docs/common_tasks:dependencies')]].

Here's an example target definition:

    ::python
    # myproject/src/main/scala/BUILD
    scala_library(name='scala',
      sources=globs('*.scala'),
      dependencies=[
        'client-lib',
        'analytics-lib',
        'static/resources/json:config',
      ],
    )

That library can then be compiled (perhaps for debugging purposes):

    ::python
    $ ./pants compile myproject/src/main/scala

You can combine library targets together into a single target using a **target alias**. More info can be found in [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]].

## See Also

* [[Compile a Library Target|pants('src/docs/common_tasks:compile')]]
* [[Define a JVM Executable|pants('src/docs/common_tasks:jvm_binary')]]
* [[Create a Bundled zip or Other Archive|pants('src/docs/common_tasks:bundle')]]
* [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]]
