# Run Tests for Your Project

## Problem

You want to run a test or test suite that you've written for your project (or several tests or test suites).

## Solution

The `test` goal will run any tests contained in the specified target. Here's an example:

    ::bash
    $ ./pants test myproject/src/test/scala:scala-tests

For Scala and Java, test suites are defined in `junit_tests` target definitions, while Python test suites are defined in `python_tests` definitions. For each test target type, you need to specify. More on these target types can be found in [[Specify a Test Suite|pants('src/docs/common_tasks:test_suite')]].

## Discussion

When you run a test using `pants test`, the output will indicate whether the test (or set of tests) has succeeded or failed and it will also provide a URL that you can navigate to to see a full report from the test, for example:

> http://localhost:57466/run/pants_run_2016_05_22_18_12_43_104
