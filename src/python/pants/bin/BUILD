# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'bin',
  sources = ['goal_runner.py', 'pants_exe.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.log',
    '3rdparty/python:setuptools',

    'src/python/pants/backend/android:plugin',
    'src/python/pants/backend/authentication:authentication',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/backend/maven_layout:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_address_mapper',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:config',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:extension_loader',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/engine',
    'src/python/pants/goal',
    'src/python/pants/goal:context',
    'src/python/pants/goal:initialize_reporting',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',

    # XXX these are necessary to parse BUILD.commons.  Should instead be
    # added as plugins to pants.ini
    'src/python/pants/backend/core/tasks:what_changed',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:checkstyle',
    'src/python/pants/backend/python:python_chroot',
    'src/python/pants/scm:git',
  ],
)

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
  compatibility='CPython>=2.7,<3',
  dependencies = [
    ':bin',
  ],
)

# This binary is for internal use only.  It adds a dep on internal_backends not meant for
# publishing in the `pantsbuild.pants` sdist.
python_binary(
  name = 'pants_local_binary',
  entry_point = 'pants.bin.pants_exe:main',
  dependencies = [
    ':bin',
    'pants-plugins/src/python/internal_backend:plugins',
  ],
)
