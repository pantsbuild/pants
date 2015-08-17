# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'jvm',
  dependencies = [
    ':jar_dependency_utils',
    'tests/python/pants_test/backend/jvm/targets',
    'tests/python/pants_test/backend/jvm/tasks',
  ]
)

python_tests(
  name = 'jar_dependency_utils',
  sources = ['test_jar_dependency_utils.py'],
  dependencies = [
    'src/python/pants/backend/jvm:jar_dependency_utils',
  ]
)