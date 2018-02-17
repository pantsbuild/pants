# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='test_infra',
  dependencies=[
    'tests/python/pants_test:base_test',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/jvm:jar_task_test_base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/engine:engine_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testinfra',
    description='Test support for writing pants plugins.',
    namespace_packages=['pants_test'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ]
  )
)

python_library(
  name = 'base_test',
  sources = ['base_test.py'],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_root',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/init',
    'src/python/pants/source',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/option/util',
  ]
)

python_library(
  name = 'int-test',
  sources = [
    'pants_run_integration_test.py'
  ],
  dependencies = [
    '3rdparty/python:ansicolors',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file',
    'src/python/pants/fs',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/testutils:file_test_util',
    'tests/python/pants_test/testutils:pexrc_util',
    # NB: Integration tests in the pants codebase find the pants script by absolute path, which
    # escapes the chroot which tests are executed in, allowing them to use files they don't
    # explicitly depend on. This dependency forces every test depending on this target to depend on
    # ~all the pants source, so the result is invalidated when changing any relevant source files. If
    # this is removed, the result of integration tests will be cached regardless of changes to
    # source files that affect their behavior. This does not occur in CI due to the use of
    # clean-all.
    # There may be a better way to do this.
    'src/python/pants/bin:pants_local_binary',
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    ':base_test',
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
