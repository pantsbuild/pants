# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='bin',
  sources=globs('*.py'),
  dependencies = [
    '3rdparty/python:ansicolors',
    '3rdparty/python:pex',
    '3rdparty/python:setproctitle',
    '3rdparty/python:twitter.common.collections',
    ':plugins',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/base:scm_project_tree',
    'src/python/pants/base:workunit',
    'src/python/pants/build_graph',
    'src/python/pants/engine',
    'src/python/pants/goal',
    'src/python/pants/goal:context',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/help',
    'src/python/pants/java:nailgun_client',
    'src/python/pants/java:nailgun_executor',
    'src/python/pants/java:nailgun_io',
    'src/python/pants/java:nailgun_protocol',
    'src/python/pants/logging',
    'src/python/pants/option',
    'src/python/pants/pantsd/subsystem:pants_daemon_launcher',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/reporting',
    'src/python/pants/reporting:report',
    'src/python/pants/source',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:filtering',
    'src/python/pants/util:memo',
  ],
)

target(
  name = 'plugins',
  dependencies = [
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/docgen:plugin',
    'src/python/pants/backend/graph_info:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info:plugin',
    'src/python/pants/backend/python:plugin',
  ],
)

# This binary's entry_point is used by the pantsbuild.pants sdist to setup a binary for
# pip installers, ie: it is why this works to get `pants` on your PATH:
# $ pip install pantsbuild.pants
# $ pants
python_binary(
  name='pants',
  entry_point='pants.bin.pants_exe:main',
  dependencies=[
    ':bin',
  ],
)

# This binary is for internal use only.  It adds deps on both internal_backends not meant for
# publishing in the `pantsbuild.pants` sdist as well as deps on backend plugins published as
# separate sdists from the core `pantsbuild.pants` sdist that this repo uses.
python_binary(
  name='pants_local_binary',
  entry_point='pants.bin.pants_exe:main',
  dependencies=[
    ':bin',
    'contrib/python/src/python/pants/contrib/python/checks/tasks/checkstyle:all',
    'pants-plugins/src/python/internal_backend:plugins',
  ],
)
