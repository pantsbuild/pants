# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_root',
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'build_file_address_mapper',
  sources = ['test_build_file_address_mapper.py'],
  dependencies = [
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'build_file_aliases',
  sources = ['test_build_file_aliases.py'],
  dependencies = [
    'src/python/pants/build_graph',
  ],
)

python_tests(
  name = 'build_file_parser',
  sources = ['test_build_file_parser.py'],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/util:strutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'build_graph',
  sources = ['test_build_graph.py'],
  dependencies = [
    '3rdparty/python:six',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'build_graph_integration',
  sources = ['test_build_graph_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'scopes',
  sources = ['test_scopes.py'],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'source_mapper',
  sources = ['test_source_mapper.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'target',
  sources = ['test_target.py'],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)
