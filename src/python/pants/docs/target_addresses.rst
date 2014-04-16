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

::

  # Fully qualified target address is the BUILD file path plus target name.
  $ ./pants goal list src/java/com/pants/examples/hello/main/BUILD:main
  src/java/com/pants/examples/hello/main/BUILD:main

  # Specify the default target, which matches the parent directory name
  $ ./pants goal list src/java/com/pants/examples/hello/main/BUILD
  src/java/com/pants/examples/hello/main/BUILD:main

  # The BUILD file name is optional.
  $ ./pants goal list src/java/com/pants/examples/hello/main
  src/java/com/pants/examples/hello/main/BUILD:main

  # Trailing forward slashes are ignored to accommodate command-line completion.
  $ ./pants goal list src/java/com/pants/examples/hello/main/
  src/java/com/pants/examples/hello/main/BUILD:main

  # Targets can be referenced relatively within the same BUILD file.
  java_library(name='application', ...)
  java_library(name='mybird',
    dependencies=[pants(':application')],
  )

Pants supports two globbing target selectors. These globbing selectors are
provided as a convenience on the command-line. For target dependencies,
explicit target names are used.

A trailing single colon specifies a glob of targets at the specified location.

::

    $ ./pants goal list tests/python/pants_test/:
    tests/python/pants_test/BUILD:base-test
    tests/python/pants_test/BUILD:test_maven_layout
    tests/python/pants_test/BUILD:test_thrift_util
    tests/python/pants_test/BUILD:all


A trailing double colon specifies a recursive glob of targets at the specified
location.

::

    $ ./pants goal list tests/python/pants_test/::
    tests/python/pants_test/BUILD:base-test
    tests/python/pants_test/BUILD:test_maven_layout
    tests/python/pants_test/BUILD:test_thrift_util
    tests/python/pants_test/BUILD:all
    tests/python/pants_test/base/BUILD:base-test
    tests/python/pants_test/base/BUILD:all
    tests/python/pants_test/base/BUILD:base
    ...
    tests/python/pants_test/tasks/BUILD:sorttargets
    tests/python/pants_test/tasks/BUILD:targets_help
    tests/python/pants_test/tasks/BUILD:what_changed
    tests/python/pants_test/testutils/BUILD:testutils
