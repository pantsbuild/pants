# Run Tests for Your Project

## Problem

You want to run a test or test suite that you've written for your project (or several tests or test suites).

## Solution

The `test` goal will run any tests contained in the specified target. Here's an example:

    ::bash
    $ ./pants test myproject/src/test/scala:scala-tests

There are several approaches to running tests. You can combine
