# Specify a Python Test Suite

## Problem

You need to define a test target for your Python library that you can run using Pants.

## Solution

Define a `python_tests` target definition that specifies which Python files will be used for testing and which library or libraries will be tested. With that target definition in place, you'll be able to run the tests like this:

    ::bash
    $ ./pants test myproject/src/test/python:tests

## Discussion

You should specify the following in a `python_tests` definition:

* A `name` for the target
* A list of `sources` specifying which files contain the tests themselves
* A list of `dependencies`
* A list of `resources` (optional). More info can be found in [[Create a Resource Bundle|pants('src/docs/common_tasks:resources')]].

Here's an example:

    ::python
    python_tests(name='python-tests',
      sources=globs('*.py'),
      dependencies=[
        'myproject/src/main/python',
      ]
    )

With that target definition, you can then run the tests using Pants:

    ::bash
    $ ./pants test myproject/src/test/python:python-tests

When you run a test, Pants will compile any libraries being tested and then run the actual tests. You should see many lines of Pants-specific output followed by the test results. Here's an example:

    ::
    18:12:43 00:00 [main]
    See a report at: http://localhost:57466/run/pants_run_2015_05_22_18_12_43_104
    18:12:43 00:00   [bootstrap]
    18:12:43 00:00   [setup]
    18:12:43 00:00     [parse]
                   Executing tasks in goals: bootstrap -> imports -> # etc.
    #
    # etc.
    #
    18:12:53 00:10     [junit]
    18:12:53 00:10       [run]
                        ..
                        Time: 0.573

                        OK (2 tests)


    Waiting for background workers to finish.
    SUCCESS

Included with the output is a URL to which you can navigate to see a report. In the example above, that URL is http://localhost:57466/run/pants_run_2015_05_22_18_12_43_104.

## See Also

* [[Run Tests for Your Project|pants('src/docs/common_tasks:test')]]
* [[Define a Test Suite for Scala and Java|pants('src/docs/common_tasks:jvm_tests')]]
