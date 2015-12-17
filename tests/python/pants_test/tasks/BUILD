# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'task_test_base',
  sources = ['task_test_base.py'],
  dependencies = [
    'src/python/pants/goal:context',
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'src/python/pants/task',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'scalastyle_integration',
  sources = ['test_scalastyle_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'builddict',
  sources = ['test_builddict.py'],
  dependencies = [
    ':task_test_base',
    'src/python/pants/backend/core/tasks:builddictionary',
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'changed_target_integration',
  sources = ['test_changed_target_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'bootstrap_jvm_tools_integration',
  sources = ['test_bootstrap_jvm_tools_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'reflect',
  sources = ['test_reflect.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:reflect',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'execution_graph',
  sources = ['test_execution_graph.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:execution_graph',
    ]
)

python_tests(
  name = 'clean_all_integration',
  sources = ['test_clean_all_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ],
  tags = {'integration'},
)
