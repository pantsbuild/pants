# Build a Python Executable (PEX)

## Problem

You need to create an executable `.pex` Python binary (aka a "PEX") out of Python source code. 

For more on PEX files see: [https://github.com/pantsbuild/pex](https://github.com/pantsbuild/pex)

If you need to create a Python library target instead, see [[Define a Python Library Target|pants('src/docs/common_tasks:python_library')]].

## Solution

Define a `python_binary` target that you can build as a PEX using the `binary` goal:

    ::bash
    $ ./pants binary myproject/src/python:my-python-binary

## Discussion

In a `python_ binary` target, you should specify:

* A `name` for the PEX
* A `source` Python file that contains a `main` function
* A list of `dependencies` (optional). This list should include only Python [[library targets|pants('src/docs/common_tasks:python_library')]] within the same project, *not* third-party dependencies. Any third-party dependencies should be specified in library targets.

**Note**: As an alternative to specifying a `source` file, you can define an `entry_point` function in your `python_binary` target. For example, specifying `entry_point='main:run'` would mean that the `main` function for the binary is the `run()` function contained in `main.py`.

Here's an example `python_binary` target:

    ::python
    python_library(name='myproject-lib',
      # Other parameters
    )

    python_binary(name='myproject-bin',
      source='main.py',
      dependencies=[
        ':myproject-lib'
      ]
    )

## See Also

* [[Run a Binary Target|pants('src/docs/common_tasks:run')]]
* [[Define a Python Library Target|pants('src/docs/common_tasks:python_library')]]
