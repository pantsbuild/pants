# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'dependencies_integration',
  sources = ['test_dependencies_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test'
  ],
  tags = {'integration'},
  timeout = 90,
)

python_tests(
  name = 'filemap_integration',
  sources = ['test_filemap_integration.py'],
  dependencies = [
    'src/python/pants/base:file_system_project_tree',
    'tests/python/pants_test:int-test'
  ],
  tags = {'integration'},
  timeout = 180,
)

python_tests(
  name = 'graph',
  sources = ['test_graph.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/bin',
    'src/python/pants/build_graph',
  ]
)

python_tests(
  name = 'list_integration',
  sources = ['test_list_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test'
  ],
  tags = {'integration'},
  timeout = 180,
)

python_tests(
  name = 'pants_engine_integration',
  sources = ['test_pants_engine_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test'
  ],
  tags = {'integration'}
)
