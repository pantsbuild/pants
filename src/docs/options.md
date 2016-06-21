Pants Options
=============

Pants is very configurable and has literally hundreds of tuneable parameters, known in Pants
parlance as _options_.

Most options are automatically set to useful defaults. However it is inevitable that sooner or
later you'll need to tweak some of them.  For example, you may want [[to pin your Pants version|pants('src/docs:install')]].

The Pants options system is fairly complex. Codebase administrators will need to understand its details
and nuances. End users, however, can usually get by with just a superficial view.

Option Scopes
-------------

Pants has many moving parts, and more can be added via custom plugins. To avoid option naming collisions,
each configurable component is qualified by a _scope_.

+ Global options belong to the global scope.
+ Options for task `task` in goal `goal` belong to the `goal.task` scope. E.g., `gen.thrift` or `compile.zinc`.
  However if the task has the same name as the goal, then the scope is just that name. E.g., `./pants list`,
  not `./pants list.list`.
+ Options for the global instance of subsystem `subsystem` belong to the `subsystem` scope. E.g., `jvm` or `cache`.
+ Options for the instance of subsystem `subsystem` belonging to some other task or subsystem with scope `scope`
  belong to the `subsystem.scope` scope. E.g., `cache.compile.zinc`.

The scope names are used to qualify the option names when setting their values, as explained in
the remainder of this document.

Basic vs. Advanced Options
--------------------------

Some options, such as `-l` to control the logging verbosity level, are
expected to be set directly by users, as needed. But most options are
expected to be configured once by a codebase administrator and not
directly modified by users. These latter options are called _advanced_
options, and are not enumerated in help messages by default.  Advanced
options may change the way projects are built and packaged, impact the
build cache or change test behavior.  For that reason, they should
usually be set in config files and checked in to the repo so that
build output is consistent, no matter which user invokes it.

To show the full list of options for a goal, including advanced
options, use `./pants <goal> --help-advanced`.  You can view
all options for all scopes with `./pants --help-all --help-advanced`.

Recursive Options
-----------------

A handful of global options, such as `-l`, are _recursive_. That is, they have a global value which
can be overridden in each scope.  This allows you, for example, to set different logging verbosity
levels in different tasks.


Option Types
------------

Option value literal formats are the same on the command-line, environment variables and in `pants.ini`,
with a couple of extra command-line conveniences.

### Boolean Options

The boolean option values are: `false`, `False`, `true`, `True`.

On the command line, you can omit the value thus: `--foo-bar` is the same as `--foo-bar=false`,
  and `--no-foo-bar` is the same as `--foo-bar=false`.

### Int and Float Options

Specify values in decimal notation: `--foo=5`, `--bar=4.5`.

### String Options

Surround strings with single or double quotes if they contain embedded spaces: `--foo="hello, world"`.

### List Options

List options can be appended to and filtered, as well as overridden.
For example, for an option `--foo` whose default value is `[1, 2]`, then in `pants.ini`:

+ `foo: 3` will yield `[1, 2, 3]`.
+ `foo: +[3, 4]` will yield `[1, 2, 3, 4]`.
+ `foo: -[1]` will yield `[2]`.
+ `foo: [3, 4]` will yield `[3, 4]`.

Multiple append and filter expressions may be delimited with commas,
allowing you to append and filter simultaneously:

+ `foo: +[3,4],-[1]` will yield `[2, 3, 4]`.

On the command line you can append single values multiple times:

+ `--foo=3 --foo=4` will yield the value `[1, 2, 3, 4]`.

Note that these command line values will be appended to the value determined from the defaults
plus the values in `pants.ini`. To override the value, use `--foo=[3, 4]`.

Filters apply to the entire list constructed so far, and will filter all appearances of the value:

+ `--foo=1 --foo=1 --foo=2 --foo=-[1]` will yield `[2, 2]`.

Filters take precedence over appends, so you cannot "add something back in":

+ `--foo=-[2] --foo=2` will yield `[1]`.


### Dict Options

Dict option values are Python-style dict literals: `--foo={"a":1,"b":2}`.

### Available Options

The options available in a given Pants-enabled codebase depend on which backends and plugins are activated.

+ View [all options]('options_reference.html') available in a "vanilla" Pants install.
+ To see a complete list of all basic options available in a given Pants-enabled codebase, enter `./pants help-all`.
+ To see global (or goal-specific) basic options, enter `./pants help (goal)`.
+ To see global (or goal-specific) basic and advanced options, enter `./pants help-advanced (goal)`.


Setting Option Values
---------------------

Every Pants option can be set in one three ways, in descending order of precendence:

+ Using a command-line flag.
+ Using an environment variable.
+ In a config file.

Config files are typically used to set codebase-wide defaults for all users.  Individual
users can then override various values using environment variables or command-line flags.

Options that aren't set by one of these three methods will fall back to a sensible default, so
that Pants will work "out of the box" in common scenarios.

### Command Line Flags

Option `option` in scope `foo.bar` can be set using the flag `--foo-bar-option=<value>`.

Global options are set with no scope qualifier, e.g., `--pants-workdir=/path/to/workdir`.

Values for single-letter flags (those that start with a single dash) can be set without the equals
sign: `-ldebug` is the same as `--level=debug` (`-l` is a synonym for `--level`).  All other flags
must use an equals sign to set a value.

There's a useful shorthand that can save some typing when setting multiple options for a single task:
If you invoke a task explicitly on the command line then you can follow that task with unqualified
options in its scope. E.g., `./pants compile.zinc --no-incremental --name-hashing`
instead of `./pants compile --no-compile-zinc-incremental --compile-zinc-name-hashing`.

Note that this shorthand requires you to mention a specific task, not just a goal: `./pants compile.zinc`
instead of just `./pants compile` as you would usually enter. All tasks in the `compile` goal will
still be executed, not just `compile.zinc`, but the `.zinc` addition is a convenience to support shorthand options.

Of course this works when specifying multiple goals, e.g.,

`./pants compile.zinc --no-incremental --name-hashing test.junit --parallel-threads=4`


### Environment Variables

Option `option` in scope `foo.bar` can be set via the environment variable `PANTS_FOO_BAR_OPTION`.
E.g., `PANTS_COMPILE_ZINC_INCREMENTAL=false`.

Global options can be set using `PANTS_GLOBAL_OPTION` as expected, but you can also omit the GLOBAL
and use `PANTS_OPTION`. E.g., `PANTS_LEVEL=debug`.

If a global option name itself starts with the word 'pants' then you can omit the repetition. E.g.,
`PANTS_WORKDIR` instead of `PANTS_PANTS_WORKDIR`.

Environment variables are overridden by command line flags, but take
precedence over settings in config files.

### Config File

The main Pants config file location is `pants.ini` in your source tree's top-level directory.
If you installed pants [[as recommended|pants('src/docs:install')]] this file should already exist.

The `pants.ini` file is an INI file parsed by
[ConfigParser](http://docs.python.org/library/configparser.html).  See
[RFC #822](http://tools.ietf.org/html/rfc822.html#section-3.1)
section 3.1.1 for the full rules python uses to parse ini file
entries.

A `pants.ini` file looks something like:

    :::ini
    [scope]
    option1: value1
    option2: value2

Sections in the `.ini` file correspond to the task name or
subsystem name, or a combination of both.

The `[DEFAULT]` section is special: its values are available in all other sections. E.g.,

    :::ini
    [DEFAULT]
    thrift_workdir: %(pants_workdir)s/thrift

    [GLOBAL]
    print_exception_stacktrace: True

    [gen.thrift]
    workdir: %(thrift_workdir)s

    [compile.zinc]
    args: [
        '-C-Tnowarnprefixes', '-C%(thrift_workdir)s',
      ]

Note that continuation lines of multiple-line values must be indented. For example, the closing
bracket in the multi-line list above.

Settings in config files are overridden by options specified in the
environment or by command line flags.

There are a few differences in using options in the config file compared to invoking them from the
command line:

  - Omit the leading double dash (`--`)
  - Dash characters (`-`) are transposed to underscores (`_`).
  - Boolean flag values are enabled and disabled by setting the value
    of the option to `True` or `False`
  - The prefix for long form options is not specified. Instead, you must organize the options
    into their appropriate sections.

### Overlaying Config Files

Sometimes it's convenient to keep `.ini` settings in more than one file. Perhaps you usually
operate Pants in one "mode", but occasionally need to use a tweaked set of settings.

Use the `--pants-config-files` command-line option to specify a second `.ini` file. Each of
this `.ini` file's values override the corresponding value in `pants.ini`, if any.
For example, if your `pants.ini` contains the section

    [test.junit]
    coverage_html_open: True
    debug: False

...and you invoke `--pants-config-files=quick.ini` and your `quick.ini` says

    [test.junit]
    coverage_html_open: False
    skip: True

...then Pants will act as if you specified

    [test.junit]
    coverage_html_open: False
    skip: True
    debug: False

Note that `--pants-config-files` is a list-valued option, so all the
idioms of lists work. You can add a third file with another invocation
of `--pants-config-files=<path>`, or you can replace the standard one
entirely with `--pants-config-files=[<list>]`.

Troubleshooting Config Files
----------------------------

### Use the Right Section Name

Section names must correspond to actual option scopes.  Use the correct section name as specified
in the help output:

    :::ini
    # Wrong
    [compile]  # The correct scope for the 'warnings' option is compile.zinc
    zinc_warnings: False

    # Right
    [compile.zinc]
    warnings: False

When in doubt, the scope is described in the heading for each option in the help output:

    ::bash
    $ ./pants compile.zinc --help

    compile.zinc options:
    Compile Scala and Java code using Zinc.

    --[no-]compile-zinc-debug-symbols (default: False)
        Compile with debug symbol enabled.
    ...

### Check the Formatting

Settings that span multiple lines should be indented.  To minimize problems, follow these
conventions:

  - Followon lines should be indented four spaces.
  - The ending bracket for lists and dicts should be indented two spaces.

Here are some examples of correctly and incorrectly formatted values:

    :::ini
    # Right
    jvm_options: [ "foo", "bar" ]

    # Right
    jvm_options: [
        "foo", "bar"
      ]

    # Wrong
    jvm_options: [ "foo",
    "bar" ]  # Followon line must be indented

    # Wrong
    jvm_options: [
        "foo", "bar"
    ] # closing bracket must be indented
