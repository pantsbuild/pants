Invoking Pants
==============

This page discusses advanced usage when invoking Pants on the command line.
We assume you already know the [[basic command-line structure|pants('src/docs:first_tutorial')]].

+ For details on how to specify target addresses, see [[Target Addresses|pants('src/docs:target_addresses')]].
+ For details on how to specify options using command-line flags, see [[Options|pants('src/docs:options')]].
+ For a list of Pants' goals and their options, see the <a href="options_reference.html">Options Reference</a>.

Order of Arguments
------------------

A simple Pants command line looks like `./pants goal target`. E.g., `./pants compile src/java/::`.

The full command line specification is:

    :::bash
    ./pants <global and fully-qualified flags> \
            <goal1.task1> <shorthand flags for task1> \
            <goal2.task2> <shorthand flags for task2> \
            ... \
            <target1> <target2> ... [-- passthrough options for last goal]

Task options can be specified using either fully-qualified flags, or shorthand flags (which
require adding the flags' task to the goal). E.g.,

    :::bash
    ./pants --level=debug compile.zinc --no-delete-scratch src::

Which is the same as:

    :::bash
    ./pants --level=debug --no-compile-zinc-delete-scratch compile src::

Many goals naturally have only one task, in which case you omit the repetition:

    :::bash
    $ ./pants --level=debug list --sep='|' examples/src/python/example:

Passthrough Args
----------------

In some cases Pants allows you to pass arguments directly through to the underlying tool it invokes.
These are specified last on the command line after a double-hyphen, and are passed through the
last goal specified.

E.g., to pass `-k foo` to `pytest` (to say "only run tests whose names contain `foo`"):

    :::bash
    $ ./pants test.pytest tests/python/pants_test/tasks -- -k foo

You can use `test` instead of `test.pytest` above; Pants then applies the passthrough args
through all tasks in `test` that support them. In this case, it would pass them to JUnit as well.
So it only makes sense to do this if you know that JUnit won't be invoked in practice (because
you're not invoking Pants on any Java tests).

