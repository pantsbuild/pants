# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base_test',
  sources = ['base_test.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:check_exclusives',
    'src/python/pants/base:address',
    'src/python/pants/base:build_configuration',
    'src/python/pants/base:build_file_address_mapper',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:build_root',
    'src/python/pants/base:config',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/goal:goal',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/base:context_utils',
  ]
)

python_library(
  name = 'int-test',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'test_binary_util',
  sources = ['test_binary_util.py',],
  dependencies = [
    ':base_test',
    'src/python/pants:binary_util',
    'src/python/pants/base:exceptions'
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    ':base_test',
    'src/python/pants/backend/maven_layout',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_tests(
  name = 'test_thrift_util',
  sources = ['test_thrift_util.py'],
  dependencies = [
    ':base_test',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    'src/python/pants:thrift_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'test_utf8_header',
  sources = ['test_utf8_header.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.lang',
    'src/python/internal_backend:plugins',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_address_mapper',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:config',
    'src/python/pants/base:dev_backend_loader',
  ]
)

target(
  name = 'integration',
  dependencies = [
    'tests/python/pants_test/android:integration',
    'tests/python/pants_test/commands:integration',
    'tests/python/pants_test/targets:integration',
    'tests/python/pants_test/tasks:integration',
    'tests/python/pants_test/python:integration',
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    ':test_binary_util',
    ':test_maven_layout',
    ':test_thrift_util',
    ':test_utf8_header',
    'tests/python/pants_test/android',
    'tests/python/pants_test/authentication:netrc',
    'tests/python/pants_test/backend',
    'tests/python/pants_test/base',
    'tests/python/pants_test/cache',
    'tests/python/pants_test/commands',
    'tests/python/pants_test/engine',
    'tests/python/pants_test/fs',
    'tests/python/pants_test/graph',
    'tests/python/pants_test/java',
    'tests/python/pants_test/net',
    'tests/python/pants_test/option',
    'tests/python/pants_test/process',
    'tests/python/pants_test/python',
    'tests/python/pants_test/reporting',
    'tests/python/pants_test/scm',
    'tests/python/pants_test/targets',
    'tests/python/pants_test/tasks',
    'tests/python/pants_test/util',
  ]
)
