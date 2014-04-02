# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':python'),
  ],
)

python_test_suite(
  name = 'python',
  dependencies = [
    pants(':test_antlr_builder'),
    pants(':test_resolver'),
    pants(':test_thrift_builder'),
    pants(':test_thrift_namespace_packages'),
  ]
)

# XXX this tests the code running the test, not the code under test!
python_tests(
  name = 'test_antlr_builder',
  sources = ['test_antlr_builder.py'],
  dependencies = [
    'src/antlr/pants/python/test:csv',
    'src/antlr/pants/python/test:eval',
  ],
)

# XXX this tests the code running the test, not the code under test!
python_tests(
  name = 'test_thrift_namespace_packages',
  sources = ['test_thrift_namespace_packages.py'],
  dependencies = [
    pants('src/thrift/com/pants/testing:duck-py'),
    pants('src/thrift/com/pants/testing:goose-py'),
  ],
)

python_tests(name = 'test_resolver',
  sources = ['test_resolver.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/python:resolver'),
  ],
)

python_tests(name = 'test_thrift_builder',
  sources = ['test_thrift_builder.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants('3rdparty/python:twitter.common.config'),
    pants('3rdparty/python:twitter.common.python'),
    pants('src/python/pants/python:thrift_builder'),
    pants('tests/python/pants:base-test'),
    pants('tests/python/pants/base:base-test')
  ]
)
