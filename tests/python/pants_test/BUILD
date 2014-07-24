# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base_test',
  sources = ['base_test.py'],
  dependencies = [
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_configuration'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:build_root'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test/base:context_utils'),
  ]
)

python_library(
  name = 'int-test',
  sources = ['pants_run_integration_test.py'],
  dependencies = [
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'test_binary_util',
  sources = ['test_binary_util.py',],
  dependencies = [
    pants(':base_test'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/base:exceptions')
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    pants(':base_test'),
    pants('src/python/pants/backend/maven_layout'),
    pants('src/python/pants/base:build_file_aliases'),
  ]
)

python_tests(
  name = 'test_thrift_util',
  sources = ['test_thrift_util.py'],
  dependencies = [
    pants(':base_test'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants:thrift_util'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'test_utf8_header',
  sources = ['test_utf8_header.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:dev_backend_loader'),
  ]
)

dependencies(
  name = 'integration',
  dependencies = [
    pants('tests/python/pants_test/targets:integration'),
    pants('tests/python/pants_test/tasks:integration'),
    pants('tests/python/pants_test/python:integration'),
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':test_binary_util'),
    pants(':test_maven_layout'),
    pants(':test_thrift_util'),
    pants(':test_utf8_header'),
    pants('tests/python/example_test/hello/greet'),
    pants('tests/python/pants_test/android'),
    pants('tests/python/pants_test/authentication:netrc'),
    pants('tests/python/pants_test/backend'),
    pants('tests/python/pants_test/base'),
    pants('tests/python/pants_test/cache'),
    pants('tests/python/pants_test/commands'),
    pants('tests/python/pants_test/engine'),
    pants('tests/python/pants_test/fs'),
    pants('tests/python/pants_test/java'),
    pants('tests/python/pants_test/net'),
    pants('tests/python/pants_test/process'),
    pants('tests/python/pants_test/python'),
    pants('tests/python/pants_test/reporting'),
    pants('tests/python/pants_test/scm'),
    pants('tests/python/pants_test/targets'),
    pants('tests/python/pants_test/tasks'),
    pants('tests/python/pants_test/util'),
  ]
)
