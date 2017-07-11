# Create an Alias for a Target

## Problem

You have a library target definition buried deep within the directory structure
of your project and want to make it easier for others to refer to that
definition (for example when specifying dependencies).

## Solution

Specify a `target` definition that refers to a target deeper in the directory
tree and acts as a proxy for it.

## Discussion

Let's say that you have a project with a `BUILD` file specifying a Scala
`scala_library` target that's deep in the directory tree, for example at
`myproject/subproject/src/main/scala`. In order for other libraries to depend
on that project, you'd need to add something like this to their dependencies:

    ::python
    
    dependencies=[
      # ...
      'myproject/src/main/scala/com/twitter/myproject:scala',
      # ...
    ]

In addition, Pants commands would be similarly verbose:

    ::bash
    
    $ ./pants compile myproject/src/main/scala/com/twitter/myproject:scala

You can simplify this by creating a `target` definition in a `BUILD` file
stored in a more convenient location in the directory tree, for example in the root directory. Here's an example:


    :: python
    # myproject/BUILD
    target(name='myproject',
      dependencies=[
        'myproject/src/main/scala/com/twitter/myproject/subproject/util:scala'
      ]
    )

Now, other projects can depend on the library target in a more concise manner:

    :: python
    dependencies=[
      # ...
      'myproject:myproject',
      # ...
    ]

Pants commands involving the target are simplified as well. Here's a comparison:

    :: bash
    
    # Without target alias
    $ ./pants compile myproject/src/main/scala/com/twitter/myproject/subproject/util:scala
    
    # With target alias
    $ ./pants compile myproject:myproject

NOTE: Proper aliases always contain exactly one destination. Using them to combine multiple library targets introduces false dependencies between the dependent and the dependency. 

See Also
--------

* [[Add a Dependency on Another Target|pants('src/docs/common_tasks:dependencies')]]
