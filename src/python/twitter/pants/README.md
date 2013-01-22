**Note**: This documentation is written during a transitional period for
pants.  If you're looking to migrate your projects from old pants to
pants.new there are a few
[[steps to follow|pants('src/python/twitter/pants/docs:migration')]] to get
your BUILD files in order.

# What is Pants?

Pants is a build tool. It is similar in some regards to make, maven,
ant, gradle, sbt, etc. However  pants differs in some important
design goals. Pants seeks to optimize for

* building multiple, dependent projects from source
* building projects in a variety of languages
* speed of build execution

At a high level, Pants reads build descriptions stored in BUILD files,
constructs a DAG of targets, and executes a specified set of goals
against those targets.

The DAG is expressed as a collection of targets (the vertices) and
dependencies (the edges). Targets and dependencies are explicitly
provided by the coder in build files, traditionally named BUILD,
dotted all over the codebase. A Pants build "sees" only the target
it's building, and the transitive dependencies of that target. It
doesn't attempt to build entire source trees.It doesn't know, or care,
about the large-scale structure of the codebase. This is the key to
its scalability.

This guide will explain how to author BUILD files and how to use the
Pants tool.

# Installing and Troubleshooting Pants Installations

See [[installation instructions|pants('src/python/twitter/pants:install')]].

# Using Pants

Pants is invoked via the pants script, usually located in the root of
your source repository. When you invoke pants you specify one or more
goals, one or more targets to run those goals against, and zero or
more command line options.

## Listing Goals

The "goal" command is an intermediate artefact of the migration
from "pants.old" to "pants.new". In the near future the goal command
will disappear.

Running pants goal with no actual goal to run will list all currently
installed goals

    [local ~/projects/science]$ ./pants goal
    Installed goals:
          binary: Create a jvm binary jar.
          bundle: Create an application bundle from binary targets.
      checkstyle: Run checkstyle against java source code.
      ......

Goals may depend on each other. For example the "compile" goal depends
on the "resolve" goal, so running compile will resolve any unresolved
jar dependencies via ivy.

## Pants Command Lines

A pants command line has the general form

    pants goal <goal(s)> <target(s)> <argument(s)>

If multiple goals are specified, you must separate goals from targets
with the gnu style "--" separator, e.g.

    pants goal compile test doc -- src/java/myproject

Flags can be placed anywhere in the command line, e.g.

    pants goal compile --compile-scalac-warnings test -- src/scala/myproject
    pants goal compile test -- src/scala/myproject --compile-scalac-warnings

Available configuration flags can be found using the --help option,
e.g.

    pants goal compile --help

## Targets, Goals, Products, Groups

As a user of pants, your core objects of interest are targets, goals
and groups. A target specifies something that exists in or should be
produced by the build. This includes sets of source files,
documentation, libraries, and others. They are the nouns of your
build. Goals are the verbs. They define actions that should be taken
on targets.

## A Simple BUILD file

Build files use a very simple, readable set of python classes for
expressing targets and dependencies. Although it looks like a DSL, it
is all constructurs and kwargs However they are really just Python
files, and so can be augmented with Python code as needed. A BUILD
file may contain multiple build targets.

### Library Dependencies

Here's a (non-real) example of a single build target:

    :::python
    scala_library(
      name = 'util',
      dependencies = [pants('3rdparty:commons-math'),
                      pants('3rdparty:flume'),
                      pants('3rdparty:heapaudit'),
                      pants('3rdparty:ostrich'),
                      pants('3rdparty:rogue'),
                      pants('3rdparty:scala-tools-time'),
                      pants('3rdparty:scalaj-collection'),
                      pants('3rdparty:s2'),
                      pants('3rdparty:thrift'),
                      pants('3rdparty:twitter-util'),
                      pants('core/src/main/scala/com/foursquare/auth'),
                      pants('core/src/main/scala/com/foursquare/i18n:localization'),
                      pants(':base')],
      sources = rglobs('*.scala'),
    )

* The type of target (in this case scala\_library) determines what
actions, if any, are taken to build it: which compilers to invoke and
so on. Pants also supports java\_library and python\_library.
* We refer to build targets by the full path of the BUILD file plus
their name, which therefore only needs to be unique within its own
BUILD file. In this case the build target is called util, and it's in,
say,core/src/main/scala/com/foursquare/base/BUILD, so the
fully-qualified name of the target is
core/src/main/scala/com/foursquare/base:util.
* The dependencies are expressed as a list of other build targets,
wrapped by the invocation pants(). Note that the dependency on
pants('core/src/main/scala/com/foursquare/auth') has no :<name>
suffix. This is because Pants offers the following shorthand: if a
target has the same name as the directory the BUILD file is in, you
can omit the name. So this dependency is short for
pants('core/src/main/scala/com/foursquare/auth:auth'). Note also the
dependency on pants(':base'). That's shorthand for "the target named
'base' in this build file."
* The sources are expressed as a list of file paths relative to the
BUILD file's directory. In most cases it's not convenient to enumerate
the files explicitly, so you can specify them with globs(<file
pattern>), which matches in the BUILD file's directory, or
rglobs(<file pattern>), which matches in the entire subtree rooted at
the BUILD file. Note that these are just functions that return a list
of file paths, so you can add or remove individual files, and
basically do any list manipulation you want.
* If the BUILD files specify a cycle, Pants will detect it and error
out (actually, it doesn't currently due to a bug, but that will be
fixed soon).

### External Dependencies

External libraries are, by convention, specified in a BUILD file in a
top-level directory called 3rdparty. These targets look like this:

    :::python
    jar_library(name='jackson',
      dependencies=[
        jar(org='org.codehaus.jackson', name='jackson-core-asl', rev='1.8.8').withSources(),
        jar(org='org.codehaus.jackson', name='jackson-mapper-asl', rev='1.8.8').withSources(),
        jar(org='org.codehaus.jackson', name='jackson-xc', rev='1.8.8').withSources()
      ]
    )

The name of the target is simply a convenient alias for an external
jar (or multiple jars). Naturally, these targets have no sources
argument. Each jar dependency is specified in the usual Ivy manner.

## pants.ini

Pants is intended to be used in a wide variety of source repositories,
and as such is highly customizable via a pants.ini file located in the
root of your source repository. You can modify a broad range of
settings here, including specific binaries to use in your toolchain,
arguments to pass to tools, etc.

# Common Tasks

## Compiling Source

    pants goal compile src/java/yourproject

## Running Tests

    pants goal test test/java/yourproject

## Packaging Binaries

To create a jar containing just the code built by a target, use the
jar goal.

    pants goal jar src/java/yourproject

Pants also supports building two variants of "fat" jars. If you add
the --jar-transitive flag to the jar goal it will include all code
built in your repository, even if it comes from a dependent target. As
an example, if projectB depends on projectA, then

    pants goal jar src/java/projectB

will only include sources for projectB, but

    pants goal jar --jar-transitive src/java/projectB

will produce a jar with sources for both projectA _and_ projectB. To
deploy a "superfat" jar that contains code for a target and all its
internal and external dependencies, use the "binary" goal.

    pants goal binary src/java/yourproject

## invalidation

the invalidate goal clears pants' internal state

    pants goal invalidate compile src/java/yourproject

invalidates pants' caches, which in most cases forces a clean build.

## cleaning up

The clean-all goal does a more vigorous cleaning of pants' state.

    pants goal clean-all

Actually removes the pants workdir, and kills any background processes
used by pants in the current repository.

## Publishing

TODO: this

# Built-In Targets

TODO: add a brief description and example of each target.

## annotation_processor

## doc

## exclude

## jar_dependency

## jar_library

## java_library

## java_protobuf_library

## java_tests

## java_thrift_library

## jvm_binary

## pants

## python_antlr_library

## python_binary

## python_egg

## python_requirement

## python_tests

## python_thrift_library

## repository

## scala_library

## scala_tests

## sources

# Extending BUILD files with goals

TODO: add description, examples of extensions

# Pants Internals

TODO: this

## .pants.d

## BUILD file parsing

## ivy resolution

## hashing

## task batching

## product mapping

## sapling?
=======

## What is Pants?

## Using Pants

#### Listing Goals

#### Pants Command Lines

#### A Simple BUILD file

#### Goals, Groups, and Targets

#### Dependencies in BUILD files

#### Extending BUILD files with goals

#### pants.ini

#### 3rdparty

## Common Tasks

#### Adding jar dependencies

#### Generating Source

#### Compiling Source

#### Running Tests

#### Packaging Binaries

#### Publishing

## Pants Internals

#### .pants.d

#### BUILD file parsing

#### ivy resolution

#### hashing

#### task batching

#### product mapping

#### sapling?

#### groups

Many goals produce output, referred to as products.
Products are .class files, .jar files, and generated source files.

Groups are a way of coordinating goals that produce similar products.
For instance scalac and javac both produce .class files. The javac
goal for a target may depend on the products of scalac on a target,
and vice versa, thus it may be necessary to interleave scalac and
javac runs, and so we put them into the "jvm" group.

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
