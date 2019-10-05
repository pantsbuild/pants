# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO: move this to src/python/pants/testinfra once we finish moving all testinfra code to src
#  and delete the code in tests.
python_library(
  name='test_infra',
  dependencies=[
    'src/python/pants/testinfra:int-test-for-export',
    'src/python/pants/testinfra:test_base',
    'src/python/pants/testinfra/jvm:jar_task_test_base',
    'src/python/pants/testinfra/jvm:nailgun_task_test_base',
    'src/python/pants/testinfra/jvm:jvm_tool_task_test_base',
    'src/python/pants/testinfra/engine:engine_test_base',
    'src/python/pants/testinfra/subsystem',
    # NB: The below targets are only here to ensure that we still include in the wheel the original
    # pants_test files. We add all transitive dependencies on testinfra code explicitly.
    'tests/python/pants_test:int-test-for-export',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/jvm:jar_task_test_base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
    'tests/python/pants_test/engine:engine_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/engine:util',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/testutils:file_test_util',
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
