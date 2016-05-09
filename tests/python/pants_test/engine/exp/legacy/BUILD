# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'dependencies_integration',
  sources = ['test_dependencies_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout = 90,
)

python_tests(
  name = 'filemap_integration',
  sources = ['test_filemap_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'graph_invalidation',
  sources = ['test_graph_invalidation.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/engine/exp/legacy:commands',
  ],
)
