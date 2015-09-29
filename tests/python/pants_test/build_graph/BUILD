# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


target(
  name = 'all',
  dependencies = [
    ':build_configuration',
    ':build_file_parser',
    ':build_graph',
  ]
)



python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'build_file_parser',
  sources = ['test_build_file_parser.py'],
  dependencies = [
    'src/python/pants/base:address',
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'build_graph',
  sources = ['test_build_graph.py'],
  dependencies = [
    'src/python/pants/base:address',
    'src/python/pants/base:address_lookup_error',
    'src/python/pants/base:target',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test'
  ],
)

python_tests(
  name = 'source_mapper',
  sources = ['test_source_mapper.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)
