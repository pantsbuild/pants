Invoking Pants
==============

This page discusses advanced usage when invoking Pants on the command line.
We assume you already know the [[basic command-line structure|pants('src/docs:first_tutorial')]].

+ For details on how to specify target addresses, see [[Target Addresses|pants('src/docs:target_addresses')]].
+ For details on how to specify options, see [[Options|pants('src/docs:options')]].
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

Fully qualified flags can be passed anywhere on the command line
before the `--` separator for passthrough args, but
shorthand flags must immediately follow the goal they apply to.

Consider the following command:

    :::bash
    ./pants --level=debug compile.zinc --no-delete-scratch --resolve-ivy-open src::

+ `--level` is a global flag.
+ The goal and task to run are `compile.zinc`.
+ The `--no-delete-scratch` is shorthand for the
  `--compile-zinc-no-delete-scratch` flag.
+ The `--resolve-ivy-open` command is a fully qualified flag and
  applies to the `resolve.ivy` task.  Although the task `resolve.ivy`
  isn't specified on the command line it implicitly runs because
  `compile.zinc` task depends on it.

You can pass options to pants using the a config file, the
environment, or command line flags. See the
[[Options|pants('src/docs:options')]] page for more details.

How to Use Shorthand Flags
--------------------------

Either fully qualified or shorthand flags can be used to pass an
option to a task. The fully qualified (or long form) options are
listed in the `help` output and the <a href="options_reference.html">Options Reference</a>.
The long form is more foolproof to use because it can go almost anywhere on
the command line, but the shorthand version can save typing.

For many goals, there is only a single task registered. For example,
to specify the `--list-sep` option for the `list` goal you could use
the long form:

    :::bash
    ./pants list --list-sep='|' examples/src/python/example:

or you could use the short form:

    :::bash
    ./pants list --sep='|' examples/src/python/example:

When a goal has multiple tasks registered, you must fully specify the
task and goal name to use the short form flag.  Here's an example of
using the long form to pass an option to the `zinc` task:

    :::bash
    ./pants --no-compile-zinc-delete-scratch compile src::

To use the shorthand form of the option, specify both goal and task
name as `compile.zinc`:

    :::bash
    ./pants  compile.zinc --no-delete-scratch src::

This is especially handy if you have lots of options to type:

    :::bash
    ./pants publish.jar --named-snapshot=1.2.3-SNAPSHOT --no-dryrun --force src/java::

You can use shorthand even when you want to pass options to multiple
tasks by listing each task.  For example:

    :::bash
    ./pants compile --compile-zinc-no-delete-scratch --resolve-ivy-open src::

can also be expressed using shorthand flags:

    :::bash
    ./pants --level=debug compile.zinc --no-delete-scratch resolve.ivy --open src::

Passthrough Args
----------------

In some cases Pants allows you to pass arguments directly through to the underlying tool it invokes.
These are specified last on the command line after a double-hyphen, and are passed through the
last goal specified.

E.g., to pass `-k foo` to `pytest` (to say "only run tests whose names contain `foo`"):

    :::bash
    ./pants test.pytest tests/python/pants_test/tasks -- -k foo

You can use `test` instead of `test.pytest` above; Pants then applies the passthrough args
through all tasks in `test` that support them. In this case, it would pass them to JUnit as well.
So it only makes sense to do this if you know that JUnit won't be invoked in practice (because
you're not invoking Pants on any Java tests).

The Pants Daemon (pantsd)
-------------------------

The `1.3.0` release of pants included an alpha release of a daemon (`pantsd`) to accelerate common
graph operations including build file parsing and source fingerprinting. As of the `1.4.0` release,
we now consider the daemon to be of late beta quality: it's nearly ready to be enabled by default!

### Benefits

The daemon caches many filesystem operations run over run, and uses watchman to invalidate that
cache. This can significantly improve the performance of incremental and noop builds (ie,
cases where relatively small portions of the repo have changed since the previous build).

### Caveats

As of `1.4.0`, there is one remaining set of caveats to using the daemon:

* Although `./pants repl` works, it is missing some advanced TTY integrations which prevent
  line editing and some control sequences from being propagated. See the
  [Daemon Beta milestone](https://github.com/pantsbuild/pants/milestone/11) for a summary.

### Usage

To enable the daemon, see the example in `pants.daemon.ini` in the root of the pantsbuild repo:

!inc(../../pants.daemon.ini)

### Rollout

The daemon will be in beta until the caveat mentioned above is addressed, but we hope to
enable the daemon by default for the [`1.5.0` release of pants](https://github.com/pantsbuild/pants/milestone/12).

Profiling Pants
---------------

There are three environment variables that profile various parts of a pants run.

* `PANTS_PROFILE` - Covers the entire run when pantsd is disabled, or the post-fork portion
  of a pantsd run.
* `PANTSC_PROFILE` - Covers the client in a pantsd run, which connects to pantsd and then
  communicates on the socket until the run completes.
* `PANTSD_PROFILE` - Covers the graph warming operations pre-fork in a pantsd run.

To enable profiling, set the relevant environment variable to a path to write a profile to, and
then run pants:

    :::bash
    PANTS_PROFILE=myprofile.prof ./pants ..

Once you have a profile file, you can use any visualizer that supports python profiles, such as
`snakeviz` or `gprof2dot`.
