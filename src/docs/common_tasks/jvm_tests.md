# Define a Test Suite for Scala or Java

## Problem

You want to define a [JUnit](http://junit.org/) test target for your Scala or Java library so that you can run those tests using Pants.

For more info on running tests, see [[Run Tests for Your Project|pants('src/docs/common_tasks:test')]].

## Solution

Create a `junit_tests` target definition for your library. With the test target definition in place, you can run the tests using the `test` goal:

    ::bash
    $ ./pants test myproject/src/test/java:tests

## Discussion

A `junit_tests` target definition should specify the following:

* A `name` for the test suite
* A list of `sources` specifying which files contain the tests themselves
* A list of `dependencies` (which in some cases will only include the library being tested)
* A list of `resources` (optional). More info can be found in [[Create a Resource Bundle|pants('src/docs/common_tasks:resources')]].

Here's an example:

    ::python
    junit_tests(name='java-tests',
      sources=rglobs('*.java'),
      dependencies=[
        'myproject/src/main/java', # Our own Java library that we're testing
      ]
    )

With that target definition, you can then run the test using Pants:

    ::bash
    $ ./pants test myproject/src/tests/java:java-tests

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
* [[Specify a Python Test Suite|pants('src/docs/common_tasks:python_tests')]]
