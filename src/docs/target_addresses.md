Target Addresses
================

Knowing how to specify exactly the targets you need is a critical skill
when using pants. This document describes target addresses and a
multitude of ways to specify them.

Pants targets ("nouns" of the build) have an `address`, a combination of
the `BUILD` file path and target name. Addresses are used to reference
targets in `BUILD` files, and from the command-line to specify what
targets to perform the given actions on.

<a pantsmark="addresses_synonyms"> </a>

You can specify targets several ways. Some are most useful when writing
`BUILD` targets, while others are useful when invoking pants on the
command-line. Most specify a single target, but globs are available too.

The following target addresses all specify the same single target.

-   Fully qualified target address is `//` plus the BUILD file's directory path plus target name:

        :::bash
        $ ./pants list //examples/src/java/org/pantsbuild/example/hello/main:main
        examples/src/java/org/pantsbuild/example/hello/main:main

-   The starting double-slash is optional if the target isn't in the top directory:

        :::bash
        $ ./pants list examples/src/java/org/pantsbuild/example/hello/main:main
        examples/src/java/org/pantsbuild/example/hello/main:main

-   Specify the default target (the target whose name matches the parent directory name):

        :::bash
        $ ./pants list examples/src/java/org/pantsbuild/example/hello/main
        examples/src/java/org/pantsbuild/example/hello/main:main

-   Relative paths and trailing forward slashes are ignored on the
    command-line to accommodate tab completion:

        :::bash
        $ ./pants list ./examples/src/java/org/pantsbuild/example/hello/main/
        examples/src/java/org/pantsbuild/example/hello/main:main

    Absolute paths are also allowed to support flexibility in scripting
    and command line use:

        :::bash
        $ pants goal list $REPO_ROOT/src/java/org/pantsbuild/example/hello/main
        src/java/org/pantsbuild/example/hello/main:main

*NB: Neither the `./` or any other relative or absolute path forms nor the trailing slash are
allowed in target addresses in ``BUILD`` files. These are just for command-line convenience.*

As a convenience, you can reference a target in the same BUILD file by starting with a
colon ``:targetname`` instead of specifying the whole path:

    :::python
    java_library(name='application', ...)
    java_library(name='mybird',
      dependencies=[':application'],
    )

To refer to a target in a top-level BUILD file, prefix its name with `//:`. (You can prefix
any absolute path with `//`, but it's mainly useful for top-level targets since ":target" is
relative.)

    :::python
    java_library(name='application', ...)
    java_library(name='mybird',
      dependencies=['//:application'],
    )

Here, `//:application` refers to the application target in the root level
BUILD file and *not* to the application target defined just above
mybird. On the command line you could reference the root level
application target with either of:

-   `$ ./pants list :application`

-   `$ ./pants list //:application`

Pants supports two globbing target selectors. These globbing selectors
are provided as a convenience on the command-line. For target
dependencies, explicit target names are used.

A trailing single colon specifies a glob of targets at the specified
location:

    :::bash
    $ ./pants list tests/python/pants_test/:
    tests/python/pants_test:base-test
    tests/python/pants_test:test_thrift_util
    tests/python/pants_test:all

A trailing double colon specifies a recursive glob of targets at the
specified location:

    :::bash
    $ ./pants list tests/python/pants_test/::
    tests/python/pants_test:base-test
    tests/python/pants_test:all
    tests/python/pants_test/base:base-test
    tests/python/pants_test/base:all
    tests/python/pants_test/base:base
    ...
    tests/python/pants_test/tasks:sorttargets
    tests/python/pants_test/tasks:targets_help
    tests/python/pants_test/tasks:what_changed
    tests/python/pants_test/testutils:testutils
