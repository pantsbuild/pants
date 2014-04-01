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
  $ ./pants goal list src/java/com/twitter/common/application/BUILD:application
  src/java/com/twitter/common/application/BUILD:application

  # Specify the default target, which matches the parent directory name
  $ ./pants goal list src/java/com/twitter/common/application/BUILD
  src/java/com/twitter/common/application/BUILD:application

  # The BUILD file name is optional.
  $ ./pants goal list src/java/com/twitter/common/application
  src/java/com/twitter/common/application/BUILD:application

  # Trailing forward slashes are ignored to accommodate command-line completion.
  ./pants goal list src/java/com/twitter/common/application/
  src/java/com/twitter/common/application/BUILD:application

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

  $ ./pants goal list src/java/com/twitter/common/application:
  src/java/com/twitter/common/application/BUILD:action
  src/java/com/twitter/common/application/BUILD:application

A trailing double colon specifies a recursive glob of targets at the specified
location.

::

  $ ./pants goal list src/java/com/twitter/common/application::
  src/java/com/twitter/common/application/BUILD:action
  src/java/com/twitter/common/application/BUILD:application
  src/java/com/twitter/common/application/http/BUILD:http
  src/java/com/twitter/common/application/modules/BUILD:applauncher
  src/java/com/twitter/common/application/modules/BUILD:lifecycle
  src/java/com/twitter/common/application/modules/BUILD:http
  src/java/com/twitter/common/application/modules/BUILD:log
  src/java/com/twitter/common/application/modules/BUILD:stats
  src/java/com/twitter/common/application/modules/BUILD:stats_export
  src/java/com/twitter/common/application/modules/BUILD:thrift
