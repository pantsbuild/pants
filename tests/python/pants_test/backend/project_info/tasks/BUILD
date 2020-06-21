# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/project_info/tasks:dependencies',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/python',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  coverage = ['pants.backend.project_info.tasks.depmap'],
  dependencies = [
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info/tasks:depmap',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/subsystem',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'filedeps',
  sources = ['test_filedeps.py'],
  dependencies = [
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/project_info/tasks:filedeps',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)
