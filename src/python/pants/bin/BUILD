# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_exe',
  sources = ['pants_exe.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/internal_backend/repositories:plugin',
    'src/python/pants/backend/android:plugin',
    'src/python/pants/backend/authentication:authentication',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/maven_layout:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_address_mapper',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:config',
    'src/python/pants/base:dev_backend_loader',
    'src/python/pants/base:rcfile',
    'src/python/pants/commands:command',

    # XXX these are necessary to parse BUILD.commons.  Should instead be
    # added as plugins to pants.ini
    'src/python/pants/backend/core/tasks:what_changed',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:checkstyle',
    'src/python/pants/backend/python:python_chroot',
    'src/python/pants/scm:git',

    # XXX The remaining are clear abstraction leaks.
    # The goal target should be goal:run_tracker but it is inseparable from goal; also
    # an abstraction leak.
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/goal:initialize_reporting',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/reporting',
  ],
)

target(
  name='pants_binary_deps',
  dependencies=[
    ':pants_exe',
    'src/python/pants/backend/python/commands:pants_old',
    'src/python/pants/commands:pants_new',
  ]
)

# 3.0 - 3.2 did not support unicode literals so we don't support these for now since it would
# take some work to make the codebase compatible.
# Additionally we force a an ascii string for python 3.3.x here.
PANTS_COMPATIBILITY = 'CPython>=2.6,<3,>=3.3'

# This binary's entry_point is used by the pantsbuild.pants sdist to setup a binary for
# pip installers, ie: it is why this works to get `pants` on your PATH:
# $ pip install pantsbuild.pants
# $ pants
# NB: The platforms below are _only_ used when building a pex from this target.  They are
# not used in the sdist generation.
python_binary(
  name = 'pants',
  entry_point = 'pants.bin.pants_exe:main',
  # TODO(John Sirois): Nuke this - we don't publish pexes so we need not build cross-platform pexes.
  platforms=[
    'current',
    'linux-x86_64',
    'macosx-10.4-x86_64',
  ],
  compatibility=PANTS_COMPATIBILITY,
  dependencies = [
    ':pants_binary_deps',
  ],
)

# This binary is for internal use only.  It adds a dep on internal_backends not meant for
# publishing in the `pantsbuild.pants` sdist.
python_binary(
  name = 'pants_local_binary',
  entry_point = 'pants.bin.pants_exe:main',
  compatibility=PANTS_COMPATIBILITY,
  dependencies = [
    ':pants_binary_deps',
    'src/python/internal_backend:plugins',
  ],
)
