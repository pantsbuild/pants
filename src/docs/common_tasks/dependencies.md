# Add a Dependency on Another Target

## Problem

You need to add a dependency for a library target in the same repository.

## Solution

Add a reference to the desired library target to the `dependencies` listed for
your target. Dependencies to other targets are typically added to
`scala_library`, `java_library`, and `python_library` targets.

## Discussion

Below is an example `python_library` definition that specifies dependencies on other targets:

    ::python
    # src/python/myproject/example/BUILD
    python_library(
      dependencies=[
        'src/python/myproject/library-a',
        'src/python/myproject/library-b:some-target',
      ],
    )

In this example, we have two dependencies, both of which reside in the same repository as our code. They are referenced by the relative path from the root of the repository, to the location of the `BUILD` file that defines the buildable target you wish to depend on.

You should always target dependencies through their library target definition (e.g. `scala_library` or `python_library`). Many projects have set up aliases that
are shorter. For more info, see
[[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]].

NOTE: In many cases, you can specify a library target path without specifying a target name. In the example above, the `src/python/myproject/library-a` library is targeted without a target name. That's because the target name, in this case, is the same as that of the directory. Here's what that `BUILD` file might look like:

    ::python
    # src/python/myproject/library-a

    target(
      name='library-a',
      dependencies=[
        # ...
      ],
    )

This is called a **default target name** and can be used whenever the target and directory names match.

## See Also

* [[Compile a Library Target|pants('src/docs/common_tasks:compile')]]
* [[Create a New Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]]
* [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]]
