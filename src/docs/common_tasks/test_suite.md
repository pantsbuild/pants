# Specify a Test Suite for Your Project

## Problem

You need to create a suite of tests that you can run using Pants' `test` goal.

## Solution

For Scala or Java, create a `junit_tests` target definition that defines your suite; for Python, create a `python_tests` definition. For both target types, you need to specify:

- A `name` for the Pants target
- A list of `sources` specifying which files contain the tests themselves
- A list of `dependencies` (which in many cases will include only the library being tested but could include others)
- A list of `resources` (optional). More info can be found in [[Create a Resource Bundle|pants('src/docs/common_tasks:resources')]]

Below is an example `junit_tests` definition followed by a `python_tests` definition:

    ::python
    junit_tests(name='scala-tests',
      sources=rglobs('*.scala'),
      dependencies=[
        'myproject/src/main/scala',
      ]
    )

    python_tests(name='python-tests',
      sources=globs('*.py'),
      dependencies=[
        'myproject/src/python',
      ]
    )

Now you can [[run the test|pants('src/docs/common_tasks:test')]] using the Pants `test` goal like this:

    ::bash
    $ ./pants test myproject/src/tests:scala-tests
