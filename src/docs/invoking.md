Invoking Pants Build
====================

This page discusses some advanced features of invoking the Pants build
tool on the command line. We assume you already know the
[[basic command-line structure|pants('src/docs:first_tutorial')]],
something like:

    :::bash
    $ ./pants goal test.junit --fail-fast bundle path/to/target path/to/another/target

For a full description of specifying target addresses, see
[[Target Addresses|pants('src/docs:target_addresses')]].
For a list of Pants' goals and their options, see the
<a href="goals_reference.html">Goals Reference</a>.

Order of Arguments
------------------

A simple Pants command line looks like <tt>./pants goal <var>goal</var> <var>target</var></tt>.
A less-simple Pants command looks like:

    :::bash
    ./pants goal <global options> <goal1> <options for goal1> <goal2> <options for goal2> \
            <target1> <target2> [-- pass-through options for last goal]

You can specify one or more goals. You can specify options for any goal right after that goal's
name:

    :::bash
    $ ./pants goal list --sep='|' examples/src/python/example:
    examples/src/python/example:readme|examples/src/python/example:pex_design|examples/sr...

Some goals are made up of tasks; to specify an option for that task, use the dotted
_goal.task_ notation:

    :::bash
    ./pants goal compile.java --no-delete-scratch src:: # compile src, keeping Java compile's "scratch files"

You can specify one or more targets to operate upon. Target specifications come after goals
and goal options on the command line.

<em>Global options</em> are the options that `./pants -h` lists, options that affect the whole
Pants run, e.g., `-ldebug`. Specify global options after "goal".

Some goals and tasks take "passthrough" args. That is, you can specify command-line args that are
passed through to some tool that Pants invoke in turn. These are specified last on the command
line after a double-hyphen like `-- foo bar` and are passed to the last goal specified. E.g., to
pass `-k list` to `pytest` (to say "only run tests whose names contain `list`") you could invoke:

    ./pants goal test.pytest tests/python/pants_test/tasks -- -k list

You could use `goal test` instead of `goal test.pytest` above; Pants then applies the
passthrough args to tools called by all of `test`, not just `test.pytest`.
This gets tricky. We happen to know we can pass `-k list` here, that `pytest` accepts passthrough
args, and that this `test` invocation upon `tests/python/...` won't invoke any other tools
(assuming nobody hid a `junit` test in the `python` directory).
