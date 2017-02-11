# Define a Python Library Target

## Problem

You need to turn your Python project into a **library target** that other libraries in your Pants workspace can use as a dependency.

If you need to create an executable Python *binary target* instead, see [[Specify a Python Executable (PEX)|pants('src/docs/common_tasks:pex')]].

## Solution

Define a `python_library` target definition that designates the library's source files, dependencies, and more.

## Discussion

A `python_library` target definition should specify the following:

* A `name` for the target
* Either a single `source` Python file or a list of `sources`
* A list of `dependencies` (optional)

Here is an example target definition:

    ::python
    python_library(name='my-python-lib',
      sources=globs('*.py'),
      dependencies=[
        'server/src/python:server-lib',
        'client/src/python:client-lib',
        'static/json:config'
      ],
    )

Now, another library or binary can depend on the target you created:

    ::python
    dependencies=[
      'myproject/src/python:my-python-lib'
    ]

## See Also

* [[Specify a Python Executable (PEX)|pants('src/docs/common_tasks:pex')]]
* [[Add a Dependency on Another Target|pants('src/docs/common_tasks:dependencies')]]
