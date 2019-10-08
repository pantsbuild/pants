# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'int-test-for-export',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    'src/python/pants/testinfra:int-test-for-export',
  ]
)

target(
  name = 'int-test',
  dependencies=[
    ':int-test-for-export',
    'src/python/pants/testinfra:int-test',
  ],
)

python_library(
  name = 'test_base',
  sources = ['test_base.py'],
  dependencies = [
    'src/python/pants/testinfra:test_base',
  ]
)

python_library(
  name = 'console_rule_test_base',
  sources = ['console_rule_test_base.py'],
  dependencies = [
    'src/python/pants/testinfra:console_rule_test_base',
  ]
)


python_library(
  name = 'task_test_base',
  sources = ['task_test_base.py'],
  dependencies = [
    'src/python/pants/testinfra:task_test_base',
  ]
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
  dependencies = [
    'src/python/pants/testinfra:interpreter_selection_utils',
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/testinfra:test_base',
    'src/python/pants/testinfra/subsystem',
  ]
)
