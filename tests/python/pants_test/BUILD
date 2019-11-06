# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='test_infra',
  dependencies=[
    ':int-test-for-export',
    ':test_base',
    'tests/python/pants_test/jvm:jar_task_test_base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/engine:engine_test_base',
    'tests/python/pants_test/engine:util',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/testutils:file_test_util',
  ],
  provides=pants_setup_py(
    name='pantsbuild.pants.testinfra',
    description='DEPRECATED: use pantsbuild.pants.testutil instead.\n\n'
                'Test support for writing Pants plugins.',
    namespace_packages=['pants_test'],
    additional_classifiers=[
      'Topic :: Software Development :: Testing',
    ],
  ),
)

python_library(
  name = 'int-test-for-export',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:int-test-for-export',
  ]
)

target(
  name = 'int-test',
  dependencies=[
    ':int-test-for-export',
    'src/python/pants/testutil:int-test',
  ],
)

python_library(
  name = 'test_base',
  sources = ['test_base.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:test_base',
  ]
)

python_library(
  name = 'console_rule_test_base',
  sources = ['console_rule_test_base.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:console_rule_test_base',
  ]
)


python_library(
  name = 'task_test_base',
  sources = ['task_test_base.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:task_test_base',
  ]
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/testutil:interpreter_selection_utils',
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ]
)
