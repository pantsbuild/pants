# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='graph',
  sources=['test_graph.py'],
  dependencies=[
    'src/python/pants/base:address',
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:parsers',
    'src/python/pants/engine/exp:targets',
  ]
)

python_tests(
  name='parsers',
  sources=['test_parsers.py'],
  dependencies=[
    'src/python/pants/engine/exp:parsers',
  ]
)
