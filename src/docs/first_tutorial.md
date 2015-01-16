First Tutorial
==============

This tutorial walks you through some first steps with Pants build:
invoking commands, looking at the files that define build-able things.
It assumes you're already familiar with
[[basic Pants build concepts|pants('src/docs:first_concepts')]].
It assumes you're
working in a source tree that already has `pants` installed (such as
Pants's own repo:
[pantsbuild/pants](https://github.com/pantsbuild/pants)).

The first time you run `pants`, try it without arguments. This makes
Pants "bootstrap" itself, downloading and compiling things it needs:

    :::bash
    $ ./pants goals

Now you're ready to invoke pants for more useful things.

You invoke pants with *goals* (like `test` or `bundle`) and the *build
targets* to use (like
`examples/tests/java/com/pants/examples/hello/greet:greet`). For
example,

    :::bash
    $ ./pants test examples/tests/java/com/pants/examples/hello/greet:greet

Goals (the "verbs" of Pants) produce new files from Targets (the
"nouns").

As a code author, you define your code's build targets in BUILD files. A
build target might produce some output file[s]; it might have sources
and/or depend on other build targets. There might be several BUILD files
in the codebase; a target in one can depend on a target in another.
Typically, a directory's BUILD file defines the target[s] whose sources
are files in that directory.

Pants Command Line
------------------

Pants knows about goals ("verbs" like `bundle` and `test`) and targets
(build-able things in your source code). A typical pants command-line
invocation looks like

    :::bash
    $ ./pants test examples/tests/java/com/pants/examples/hello/greet:greet

Looking at the pieces of this we see

`./pants`<br>
That `./` isn't a typo. A source tree that's been set up with Pants
build has a `pants` executable in its top-level directory.

The first time you run `./pants`, it might take a while: it will probably auto-update by
downloading the latest version.

`test`<br>
`test` is a *goal*, a "verb" that Pants knows about. The `test` goal runs tests and reports results.

Some goals are `gen` (generate code from Thrift, Antlr, Protocol
Buffer), `compile`, `run` (run a binary), and `test` (run tests and report results). Pants
knows that some of these goals depend on each other. E.g., in this
example, before it run tests, it must compile the code.

You can specify more than one goal on a command line. E.g., to run
tests *and* run a binary, we could have said `./pants test run ...`

`examples/tests/java/com/pants/examples/hello/greet:greet`<br>
This is a *build target*, a "build-able" thing in your source code. To
define these, you set up configuration files named `BUILD` in your
source code file tree. (You'll see more about these later.)

Targets can depend on other targets. E.g., a test target normally depends on another target
containing "library" code to test; to build and run the test code, Pants also first builds the
library code.

You can specify more than one target on a command line. Pants will carry
out its goals on all specified targets. E.g., you might use this to
to run a few directories' worth of tests.

### Output

Pants produces files, both build outputs and intermediate files
generated "along the way". These files live in directories under the
top-level directory:

`dist/`<br>
By default, build outputs go in the `dist/` directory. So far, you've
just run the `test` goal, which doesn't output a file. But if you'd
instead invoked, for example, the `bundle` goal on a `jvm_app` target,
Pants would have populated this directory with many JVM `.jar` files.

`.pants.d/`<br>
Intermediate files go in the `.pants.d/` directory. You don't want to
rely on files in there; if the Pants implementation changes, it's likely
to change how it uses intermediate files. You don't want to edit/delete
files in there; you may confuse Pants. But if you want to peek at some
generated code, the code is probably in here somewhere.

### Multiple Goals, Multiple Targets

You can specify multiple goals and multiple targets. Pants applies all
the goals to all the targets, skipping things that wouldn't make sense.
E.g., you could

-   Invoke `test` and `run` goals to both run tests and run a binary.
-   Specify both test and binary targets.

In this example, it doesn't make sense to run a binary target as a test, so
Pants doesn't do that.

<a pantsmark="tut_goal_target_mismatch"></a>

*Goal-Target Mismatch*

One tricky side effect of this is accidental *goal-target mismatch*: You
can invoke a goal that doesn't make sense for a target. E.g., you can
invoke the `test` goal on a target that's not actually a test target. Pants won't
complain. It knows that it should compile code before it tests it; it
will happily compile the build targets. If you're not watching closely,
you might see a lot of output scrolling past and think it was running
tests.

### Command-line Options

You can specify some details of Pants' actions by means of command-line options. E.g., you could
tell Pants to "fail fast" on the first `junit` test failure instead of running and reporting all
`junit` tests like so:

    :::bash
    $ ./pants test.junit --fail-fast examples/tests/java/com/pants/examples/hello/greet:greet

Here, `test` has become `test.junit`. The `test` goal is made up of parts, or *tasks*: `test.junit`,
`test.pytest`, and `test.specs`. We want to specify a flag to the `test.junit` task, so we
specify that part on the command line. (Pants still runs the other parts of the `test` goal.
The dotted notation tells Pants where to apply options.)

We entered the `--fail-fast` flag after `test.junit` but before the target. Command-line flags
for a goal or task go immediately after that goal or task.

You can specify options for more than one part of a goal. For example,

    :::bash
    $ ./pants test.junit --fail-fast test.pytest --options='-k seq' examples/tests::

Here, the `--fail-fast` flag affects `test.junit` and `--options` affects `test.pytest`.

Pants has some global options, options not associated with just one goal. For example,
If you pass the global `-ldebug` flag after the word `goal` but before any particular goal or
task, you get verbose debug-level logging for all goals:

    :::bash
    $ ./pants -ldebug test examples/tests/java/com/pants/examples/hello/greet:
    09:18:53 00:00 [main]
                   (To run a reporting server: ./pants server)
    09:18:53 00:00   [bootstrap]
    09:18:54 00:01   [setup]
    09:18:54 00:01     [parse]DEBUG] Located Distribution(u'/Library/Java/JavaVirtualMachines/jdk1.7.0_60.jdk/Contents/Home/bin', minimum_version=None, maximum_version=None jdk=False) for constraints: minimum_version None, maximum_version None, jdk False
    DEBUG] Selected protoc binary bootstrapped to: /Users/lhosken/.pants.d/bin/protobuf/mac/10.9/2.4.1/protoc
    DEBUG] Selected thrift binary bootstrapped to: /Users/lhosken/.pants.d/bin/thrift/mac/10.9/0.5.0-finagle/thrift
       ...lots of build output...

For details about the Pants command line, see [[Invoking Pants|pants('src/docs:invoking')]].

### Help

To get help about a Pants goal, invoke <tt>./pants *goalname* -h</tt>. This lists
command-line options for that goal. E.g.,

    :::bash
    $ ./pants test -h

    test: Test compiled code.

    test.specs
      -h, --help              show this help message and exit
      --jvm-options <option>...
                              Run the jvm with these extra jvm options. (default: [])
      --args <arg>...         Run the jvm with these extra program args. (default: [])
      --[no-]debug            Run the jvm under a debugger. (default: None)
      --confs _TEST.SPECS_CONFS__
                              Use only these Ivy configurations of external deps.
                              (default: [u'default'])

    ...more test options...

    test.pytest
      -h, --help              show this help message and exit
      --timeout _TEST.PYTEST_TIMEOUT__
                              Number of seconds to wait for http connections.
                              (default: 0)


    ...many more test options...

The `test` goal is made up of parts, or *tasks*: `test.junit`, `test.pytest`, and `test.specs`.
Command-line options apply to those tasks. The goal's help groups options by task. E.g., here, it
shows the `test.spec` ` --jvm-options` option with `test.specs`.

For a list of available goals, `./pants goals`.

For help with things that aren't goals (global options, other kinds of help), use

    :::bash
    $ ./pants -h

If you want help diagnosing some strange Pants behavior, you might want verbose output.
To get this, instead of just invoking `./pants`, set some environment variables and request
more logging: `PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants -debug`.

BUILD Files
-----------

When we ran the `pants test` goal, we told pants what target to build, but where are these
targets defined? Scattered around the source tree are `BUILD` files. These `BUILD` files
define targets. For example, this code snippet of `java/com/pants/examples/hello/main/BUILD`
defines two targets: the app we ran and the binary that contains its code.
These targets are named `main` (of type `jvm_app`) and and `main-bin` (of type `jvm_binary`):

!inc[start-after=Like Hello World&end-before=README page](../../examples/src/java/com/pants/examples/hello/main/BUILD)

Those `dependencies` statements are interesting.
The `main-bin` build target depends on other build targets;
its `dependencies` lists those.
To build a runnable Java binary, we need to first compile its dependencies.
The `main-bin` binary's dependency,
`'examples/src/java/com/pants/examples/hello/greet'`, is the *address* of
another target. Addresses look, roughly, like `path/to/dir:targetname`. We can see this build
target in the `.../hello/greet/BUILD` file:

!inc[start-after=see LICENSE](../../examples/src/java/com/pants/examples/hello/greet/BUILD)

Pants uses dependency information to figure out how to build your code.
You might find it useful for other purposes, too. For example, if you
change a library's code, you might want to know which test targets
depend on that library: you might want to run those tests to make sure
they still work.

### Anatomy of a `BUILD` Target

A target definition in a `BUILD` file looks something like

    :::python
    scala_library(
      name='util',
      dependencies = ['3rdparty:commons-math',
                      '3rdparty:thrift',
                      'src/main/scala/com/foursquare/auth',
                      ':base'],
      sources=globs('*.scala'),
    )

Here, `scala_library` is the target's *type*. Different target types
support different arguments. The following arguments are pretty common:

**name**<br>
We use a target's name to refer to the target. This argument isn't just
"pretty common," it's required. You use names on the command line to
specify which targets to operate on. You also use names in `BUILD` files
when one target refers to another, e.g. in `dependencies`:

**dependencies**<br>
List of things this target depends upon. If this target's code imports
code that "lives" in other targets, list those targets here. If this
target imports code that "lives" in `.jar`s/`.egg`s from elsewhere,
refer to them here.

**sources**<br>
List of source files. The `globs` function is handy here.

The Usual Commands
------------------

**Make sure code compiles and tests pass:**<br>
Use the `test` goal with the targets you're interested in. If they are
test targets, Pants runs the tests. If they aren't test targets, Pants
will still compile them since it knows it must compile before it can
test.

    :::bash
    $ pants goal test src/java/com/myorg/myproject tests/java/com/myorg/myproject

**Get Help**<br>
Get the list of goals:

    :::bash
    $ ./pants goals

Get help for one goal, e.g., test:

    :::bash
    $ ./pants test -h

Next
----

To learn more about working with Python projects, see the
[[Python Tutorial|pants('examples/src/python/example:readme')]].

To learn more about working with Java/JVM projects, see the
[[Java Tutorial|pants('examples/src/java/com/pants/examples:readme')]]
