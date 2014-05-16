# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base_test',
  sources = ['base_test.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_root'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/targets:common'),
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    pants(':base_test'),
  ]
)

python_tests(
  name = 'test_thrift_util',
  sources = ['test_thrift_util.py'],
  dependencies = [
    pants(':base_test'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants:thrift_util'),
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':test_maven_layout'),
    pants(':test_thrift_util'),
    pants('tests/python/example_test/hello/greet'),
    pants('tests/python/pants_test/authentication:netrc'),
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
  ]
)
