# Define a JVM Executable

## Problem

You need to specify a Scala or Java **binary target** that you can [[compile|pants('src/docs/common_tasks:compile')]] and/or [[run directly|pants('src/docs/common_tasks:run')]].

If you need to specify a Scala or Java *library target*, see [[Create a New Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]].

## Solution

Create a `jvm_binary` target definition for your project that specifies which `scala_library` or `java_library` target will be included in the binary (you can also include several).

## Discussion

In any `jvm_binary` target you must specify the following:

* A `name` for the target
* A `basename` that will be used as the basis of the filename if you [[bundle|pants('src/docs/common_tasks:bundle')]] the target using a `jvm_app` target
* The `main` function which serves as the executable's entry point.
* A list of `dependencies` that must include at least one `scala_library` or `java_library` target. More info can be found in [[Add a Dependency from Source|pants('src/docs/common_tasks:dependencies')]].
* A list of file `bundles` for use as static assets (optional). More info can be found in [[Specify a File Bundle|pants('src/docs/common_tasks:file_bundles')]].

Here's an example `jvm_binary` definition:

    ::python
    jvm_binary(name='bin',
      basename='myproject-bin',
      main='com.acme.myproject.Main',
      dependencies=[
        'server-lib/src/main/java',
        'analytics-lib/src/main/java',
      ],
      bundles=[
        bundle(fileset=globs('assets/*'))
      ]
    )

## See Also

* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
* [[Specify a File Bundle|pants('src/docs/common_tasks:file_bundles')]]
