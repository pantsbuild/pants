# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='test_infra',
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
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/source',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/option/util',
  ],
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
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/testutils:file_test_util',
  ],
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    ':base_test',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)
