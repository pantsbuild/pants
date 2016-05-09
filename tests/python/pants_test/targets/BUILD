# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
)

python_tests(
  name = 'unknown_arguments_integration',
  sources = ['test_unknown_arguments_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'sort_targets',
  sources = ['test_sort_targets.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'java_agent',
  sources = ['test_java_agent.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'jvm_app_integration',
  sources = ['test_jvm_app_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'scala_library',
  sources = ['test_scala_library.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'scala_library_integration',
  sources = ['test_scala_library_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)
