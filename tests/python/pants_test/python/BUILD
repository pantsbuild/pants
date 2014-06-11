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
    '3rdparty/python:antlr-3.1.3',
    'src/antlr/pants/backend/python/test:csv',
    'src/antlr/pants/backend/python/test:eval',
    'src/python/pants/backend/python:python_setup',
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
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/backend/python:resolver'),
  ],
)

python_tests(name = 'test_thrift_builder',
  sources = ['test_thrift_builder.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.config'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('3rdparty/python:mock'),
    pants('src/python/pants/backend/codegen/targets:python'),
    pants('src/python/pants/backend/python:thrift_builder'),
    pants('tests/python/pants_test/base:context_utils'),
    pants('tests/python/pants_test:base_test'),
  ]
)
