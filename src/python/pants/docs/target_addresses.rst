Target Addresses
================

Knowing how to specify exactly the targets you need is a critical skill when
using pants. This document describes target addresses and a multitude of ways
to specify them.

Pants targets ("nouns" of the build) have an ``address``, a combination of the
``BUILD`` file path and target name. Addresses are used to reference targets
in ``BUILD`` files, and from the command-line to specify what targets to
perform the given actions on.

You can specify targets several ways. Some are most useful when writing
``BUILD`` targets, while others are useful when invoking pants on the
command-line. Most specify a single target, but globs are available too.

The following target addresses all specify the same single target.

* Fully qualified target address is the BUILD file path plus target name::

    $ ./pants goal list src/java/com/pants/examples/hello/main:main
    src/java/com/pants/examples/hello/main:main

* Specify the default target, which matches the parent directory name::

    $ ./pants goal list src/java/com/pants/examples/hello/main
    src/java/com/pants/examples/hello/main:main

* Relative paths and trailing forward slashes are ignored on the command-line to accommodate tab
  completion::

    $ ./pants goal list ./src/java/com/pants/examples/hello/main/
    src/java/com/pants/examples/hello/main:main

  *NB: Neither the `./` or any other relative path form nor the trailing slash are not allowed in
  target addresses written down in BUILD files - these affordances are just for ease of command
  line specification of target addresses.*


As a convenience, targets can be referenced relatively within the same BUILD file::

    java_library(name='application', ...)
    java_library(name='mybird',
      dependencies=[pants(':application')],
    )

To refer to a target in a top-level BUILD file, prefix the target name with ``//:``. (You can
prefix any absolute path with //, but it's mainly useful for top-level targets since ":target"
is relative.) ::

    java_library(name='application', ...)
    java_library(name='mybird',
      dependencies=[pants('//:application')],
    )

Here `//:application` refers to the `application` target in the root level BUILD file and *not*
to the `application` target defined just above `mybird`.  On the command line you could reference
the root level `application` target with either of:

* ::

    $ ./pants goal list :application

* ::

    $ ./pants goal list //:application


Pants supports two globbing target selectors. These globbing selectors are
provided as a convenience on the command-line. For target dependencies,
explicit target names are used.

A trailing single colon specifies a glob of targets at the specified location::

    $ ./pants goal list tests/python/pants_test/:
    tests/python/pants_test:base-test
    tests/python/pants_test:test_maven_layout
    tests/python/pants_test:test_thrift_util
    tests/python/pants_test:all


A trailing double colon specifies a recursive glob of targets at the specified
location::

    $ ./pants goal list tests/python/pants_test/::
    tests/python/pants_test:base-test
    tests/python/pants_test:test_maven_layout
    tests/python/pants_test/BUILD:test_thrift_util
    tests/python/pants_test:all
    tests/python/pants_test/base:base-test
    tests/python/pants_test/base:all
    tests/python/pants_test/base:base
    ...
    tests/python/pants_test/tasks:sorttargets
    tests/python/pants_test/tasks:targets_help
    tests/python/pants_test/tasks:what_changed
    tests/python/pants_test/testutils:testutils
