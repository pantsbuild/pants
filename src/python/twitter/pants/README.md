**Note**: This documentation is written during a transitional period for
pants.  If you're looking to migrate your projects from old pants to
pants.new there are a few
[[steps to follow|pants('src/python/twitter/pants/docs:migration')]] to get
your BUILD files in order.

# What is Pants?

Pants is a build tool. This document introduces Pants to folks who want to use
it to build code. If someone else has already
[[set up your codebase to work with Pants|pants('src/python/twitter/pants/docs:setuprepo')]]
and you want to know how to get your code built, read on.
If you're setting up pants with some new code and discover that it doesn't
know about your tools/compilers, you'll also want to read
[[Pants Internals|pants('src/python/twitter/pants/docs:internals')]]
to learn how to add support for these tools to Pants.

Pants is similar to make, maven, ant, gradle, sbt, etc.;
but pants differs in some important design goals. Pants optimizes for

* building multiple, dependent projects from source
* building projects in a variety of languages
* speed of build execution

This guide explains how to use Pants and author its BUILD files.

You invoke pants with a _goal_ (like `test` or `compile`) and the
_build targets_ to use (like
`src/main/java/com/twitter/common/util/BUILD:util`). For example,

    pants goal test src/main/java/com/twitter/common/util/BUILD:util

Goals (the "verbs" of Pants) produce new files from Targets (the "nouns").

As a code author, you define your code's _build targets_ in BUILD files.
A build target might produce some output file[s];
it might have sources and/or depend on other build targets.
There might be several BUILD files in the codebase; a target in
one can depend on a target in another. Typically, a directory's BUILD
file defines the target[s] whose sources are files in that directory.
Pants reads BUILD files and computes the dependency graph of build targets.

For example, a BUILD file might define a library buildable from the `*.py`
files in its directory, depending on another target, `3rdparty/thrift-0.7`.

    # commons/src/python/twitter/common/rpc/BUILD 2013 February
    python_library(name = 'rpc',
      sources = globs('*.py'),
      dependencies = [ '3rdparty/python:thrift-0.7' ])

Pants looks at the build targets (and their
dependencies and <em>their</em> dependencies, and so on) to determine
what needs to be tested/compiled. A goal can depend on another; e.g., if you
invoke the `test` goal but haven't compiled, pants knows to compile first.

A _product_ is the output of a goal: `.class` files, `.jar` files,
generated source files, etc.

A Pants build "sees" only the target it's building and the transitive
dependencies of that target. It doesn't attempt to build entire source trees.
This approach works well for a big repository containing several projects,
where a tool that insists on building everything would bog down.

# Installing and Troubleshooting Pants Installations

See [[installation instructions|pants('src/python/twitter/pants:install')]].

# Using Pants

Pants is invoked via the `pants` script, usually located in the root of
your source repository. When you invoke pants, you specify one or more
goals, one or more targets to run those goals against, and zero or
more command line options.

A pants command line has the general form

    pants goal <goal(s)> <target(s)> <option(s)>

Options don't need to be at the end. These both work:

    pants goal compile --compile-scalac-warnings test src/main/scala/myproject
    pants goal compile test src/main/scala/myproject --compile-scalac-warnings

To see a goal's configuration flags, use `pants goal help _goal_`, e.g.

    pants goal help compile

(The `goal` command is an intermediate artifact of the
migration from "pants.old" to "pants.new". In the near future, the `goal`
command will disappear. We'll use `pants` _foo_ instead of `pants goal` _foo_.)

**Goals available:** Run `pants goal` to list all installed goals:

    [local ~/projects/science]$ ./pants goal
    Installed goals:
      binary: Create a jvm binary jar.
      bundle: Create an application bundle from binary targets.
      checkstyle: Run checkstyle against java source code.
      ......

# BUILD Files

A BUILD file defines build targets. `pants` uses the Python
interpreter to parse the BUILD files; thus, build targets look a lot like Python
constructors with keyword args and can be augmented with Python code as needed.
A BUILD file may contain multiple build targets.

## Parts of a Typical BUILD Target

A `BUILD` target looks something like this:

    :::python
    scala_library(
      name = 'util',
      dependencies = ['3rdparty:commons-math',
                      '3rdparty:thrift',
                      'src/main/scala/com/foursquare/auth',
                      ':base'],
      sources = rglobs('*.scala'),
    )

Different target types support different arguments. The following parts of
a BUILD target are pretty common:

**type** A target's type, here `scala_library`, expresses, roughly, the
important thing you can build from this target.
Some target types: `python_binary`, `python_library`, `jvm_binary`, and
`java_library`. A `binary` is a runnable thing. A `library` isn't runnable,
but might be linked together with other things to produce a binary.

**name** We use a target's name to refer to the target; this name should be
unique within its BUILD file. You use this name at the command line, e.g.,
the `util` in `pants goal compile foo/BUILD:util`. You also use this name
in BUILD files when one target refers to another, e.g., in `dependencies`:

**dependencies** List of other targets which this target depends upon. Normally,
these targets define the things that this target imports.
The dependency on `src/main/scala/com/foursquare/auth` has no `:<name>`
suffix. This uses a shorthand: if a target's name is the same as its BUILD
file's directory, you can omit the name. This dependency is short for
`pants('src/main/scala/com/foursquare/auth/BUILD:auth')`. The
`pants(':base')` dependency is shorthand for "the target named 'base' in this
BUILD file."
If dependencies specify a cycle, Pants detects it and errors out.

**sources** List of source files. The `globs('*.java')` function or
`rglobs('*.java')` recursive glob function could come in handy here.

## Library Targets

To define an "importable" thing, you want a library target type, such as
`java_library`, `python_library`, `jar`, or `python_dependency` (Python egg).

    :::python
    scala_library(
      name = 'util',
      dependencies = ['3rdparty:commons-math',
                      '3rdparty:thrift',
                      'core/src/main/scala/com/foursquare/auth',
                      ':base'],
      sources = rglobs('*.scala'),
    )

A target whose code imports this target's code should list this target
in its `dependencies`.

## Binary Targets

To define a "runnable" thing, you want a `jvm_binary` or `python_binary` target.
A binary probably has a `main` and dependencies. (We encourage a binary's
main to be separate from the libraries it uses to run, if any.)

    :::python
    jvm_binary(name = 'junit-runner-main',
      main = 'com.twitter.common.testing.runner.JUnitConsoleRunner',
      dependencies = [ ':junit-runner' ])

## External Dependencies

Not everything's source code is in your repository.
By convention, we keep build information about external libraries in a
directory tree whose root is called `3rdparty.`

*Java Jars*

    :::python
    jar_library(name='jackson',
      dependencies=[
        jar(org='org.codehaus.jackson', name='jackson-core-asl', rev='1.8.8').withSources(),
        jar(org='org.codehaus.jackson', name='jackson-mapper-asl', rev='1.8.8').withSources(),
        jar(org='org.codehaus.jackson', name='jackson-xc', rev='1.8.8').withSources()
      ]
    )

The target name is a convenient alias for an external
jar (or, as in this example, multiple jars). These `jar`
targets have no `sources` argument, but instead the
information `ivy` uses to fetch the jars.

*Python*

    :::python
    python_library(
      name='beautifulsoup',
      dependencies=[python_requirement('BeautifulSoup==3.2.0')]
    )
    python_library(
      name='markdown',
      dependencies=[python_requirement('markdown')]
    )

The target name is a convenient alias. The `dependencies` is a list of one
or more `python_requirement` targets. The `python_requirement` can refer
to a `pkg_resources`
[requirements string](http://packages.python.org/distribute/pkg_resources.html#requirements-parsing).
Pants looks in a few places for Python `.egg`s as configured in your
`python.ini` file's `python-repos` section.

To use the external Python module, another python target could have a
dependency:

    :::python
    python_binary(name = 'mach_turtle',
      source = 'mach_turtle.py',
      dependencies = [pants('3rdparty/python:beautifulsoup')]
    )

...and the Python script's import would look like

    :::python
    from BeautifulSoup import BeautifulSoup

## Test Targets

Your test code might live in a directory separate from the main source tree.
BUILD files defining test targets probably live in that directory tree.

    :::python
    # in test/scala/com/twitter/common/args/BUILD
    scala_tests(name = 'args',
      dependencies = [
        '3rdparty:specs',
        'src/scala/com/twitter/common/args:flags',
        'src/java/com/twitter/common/args:args',
      ],
      sources = rglobs('*Spec.scala'))

The test target depends upon the targets whose code it tests. This isn't just
logical, it's handy, too: you can compute dependencies to figure out what tests
to run if you change some target's code.

    # Forgot your test's name but know you changed src/main/python/foo:foo?
    pants goal test `./pants goal dependees src/main/python/foo:foo`

    # Run dependees' tests, for src/main/python/foo:foo too.
    pants goal test `./pants goal dependees src/main/python/foo:foo --dependees-transitive`

# pants.ini

Pants is intended to be used in a wide variety of source repositories,
and as such is highly customizable via a `pants.ini` file located in the
root of your source repository. You can modify a broad range of
settings here, including specific binaries to use in your toolchain,
arguments to pass to tools, etc.

# Common Tasks

**Compiling**

    pants goal compile src/main/java/yourproject

**Running Tests**

    pants goal test src/test/java/yourproject

**Packaging Binaries**

To create a jar containing just the code built by a target, use the
`jar` goal:

    pants goal jar src/main/java/yourproject

To deploy a "fat" jar that contains code for a `jvm_binary` target and its
dependencies, use the `binary` goal and the `--binary-deployjar` flag:

    pants goal binary --binary-deployjar src/main/java/yourproject

**Invalidation**

The `invalidate` goal clears pants' internal state.

    pants goal invalidate compile src/main/java/yourproject

invalidates pants' caches. In most cases, this forces a clean build.

**Cleaning Up**

The `clean-all` goal does a more vigorous cleaning of pants' state.

    pants goal clean-all

Actually removes the pants workdir, and kills any background processes
used by pants in the current repository.

**Publishing**

TODO: this

**Adding jar dependencies**

TODO: this

**Generating Source**

TODO: this

# Built-In Targets

TODO: add a brief description and example of each target.

## annotation_processor

## exclude

## jar

## jar_library

## java_library

## java\_protobuf_library

## java_tests

## java\_thrift_library

## jvm_binary

## page

## pants

## python\_antlr_library

## python_binary

## python_requirement

## python_tests

## python\_thrift_library

## repository

## scala_library

## scala_tests

## sources

# Extending BUILD files with goals

TODO: add description, examples of extensions

=======

## Credits

Pants was originally written by John Sirois.

Major contributors in alphabetical order:

- Alec Thomas
- Benjy Weinberger
- Bill Farner
- Brian Wickman
- David Buchfuhrer
- John Sirois
- Mark McBride

If you are a contributor, please add your name to the list!
