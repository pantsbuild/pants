Invoking Pants Build
====================

This page discusses some advanced features of invoking the Pants build
tool on the command line. We assume you already know the
[[basic command-line structure|pants('src/docs:first_tutorial')]],
something like:

    :::bash
    $ ./pants test.junit --fail-fast bundle path/to/target path/to/another/target

For a full description of specifying target addresses, see
[[Target Addresses|pants('src/docs:target_addresses')]].
For a list of Pants' goals and their options, see the
<a href="options_reference.html">Options Reference</a>.

Order of Arguments
------------------

A simple Pants command line looks like <tt>./pants <var>goal</var> <var>target</var></tt>.
A less-simple Pants command looks like:

    :::bash
    ./pants <global options> <goal1> <options for goal1> <goal2> <options for goal2> \
            <target1> <target2> [-- pass-through options for last goal]

You can specify one or more goals. You can specify options for any goal right after that goal's
name:

    :::bash
    $ ./pants list --sep='|' examples/src/python/example:
    examples/src/python/example:readme|examples/src/python/example:pex_design|examples/sr...

Some goals are made up of tasks; to specify an option for that task, use the dotted
_goal.task_ notation:

    :::bash
    # compile src, keeping Java compile's "scratch files"
    ./pants compile.java --no-delete-scratch src::

You can specify one or more targets to operate upon. Target specifications come after goals
and goal options on the command line.

<em>Global options</em> are the options that `./pants -h` lists, options that affect the whole
Pants run, e.g., `-ldebug`. Specify global options after "goal".

When setting a value for an option, beware spaces. For example, `-l debug` and `--level debug`
don't do what you want. If you're tempted to put a space between an option and its value, use an
equals sign instead: `--level=debug`, `-ldebug`, and even `-l=debug` all work.

Some goals and tasks take "passthrough" args. That is, you can specify command-line args that are
passed through to some tool that Pants invoke in turn. These are specified last on the command
line after a double-hyphen like `-- foo bar` and are passed to the last goal specified. E.g., to
pass `-k list` to `pytest` (to say "only run tests whose names contain `list`") you could invoke:

    ./pants test.pytest tests/python/pants_test/tasks -- -k list

You could use `test` instead of `test.pytest` above; Pants then applies the
passthrough args to tools called by all of `test`, not just `test.pytest`.
This gets tricky. We happen to know we can pass `-k list` here, that `pytest` accepts passthrough
args, and that this `test` invocation upon `tests/python/...` won't invoke any other tools
(assuming nobody hid a `junit` test in the `python` directory).

Setting Options Other Ways
--------------------------

Instead of passing an option on the command line, you can set an environment variable or change
an option in an `.ini` file. Pants "looks" for an option value on the command line, environment
variable, and `.ini` file; it uses the first it finds.
For a complete, precedence-ordered list of places Pants looks for option values, see the
`Options` docstring in [src/python/pants/option/options.py]
(https://github.com/pantsbuild/pants/blob/master/src/python/pants/option/options.py).

### `PANTS_...` Environment Variables

Each goal option also has a corresponding environment variable. For example, either of these
commands opens a coverage report in your browser:

    :::bash
    $ ./pants test.junit --coverage-html-open examples/tests/java/org/pantsbuild/example::

    $ PANTS_TEST_JUNIT_COVERAGE_HTML_OPEN=1 ./pants test examples/tests/java/org/pantsbuild/example::

Pants checks for an environment variable whose name is `PANTS` + the goal name (or goal+task name)
+ the option name; all of these in all-caps, joined by underscores (instead of dots or hyphens).

### `pants.ini` Settings File

Pants can also read command-line options (and other options) from an `.ini` file. For example, if
your `pants.ini` file contains

    [test.junit]
    coverage_html_open: True

...then whenever Pants carries out the `test.junit` task, it will behave as if you passed
`test.junit --coverage-html-open`. If an environment variable and an `.ini` configuration both
specify a value for some option, the environment variable "wins".

### Overlay `.ini` Files with `--config-override`

Sometimes it's convenient to keep `.ini` settings in more than one file. Perhaps you usually
operate Pants in one "mode", but occasionally need to use a tweaked set of settings.

Use the `--config-override` command-line option to specify a second `.ini` file. Each of
this `.ini` file's values override the corresponding value in `pants.ini`, if any.
For example, if your `pants.ini` contains the section

    [test.junit]
    coverage_html_open: True
    debug: False

...and you invoke `--config-override=quick.ini` and your `quick.ini` says

    [test.junit]
    coverage_html_open: False
    skip: True

...then Pants will act as if you specified

    [test.junit]
    coverage_html_open: False
    skip: True
    debug: False
