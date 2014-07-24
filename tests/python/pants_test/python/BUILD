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

python_test_suite(
  name = 'integration',
  dependencies = [
    pants(':interpreter_selection_integration'),
    pants(':python_repl_integration'),
    pants(':python_run_integration'),
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
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/backend/python:resolver'),
    pants('src/python/pants/util:contextutil'),
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
    pants('src/python/pants/base:build_file_aliases'),
    pants('tests/python/pants_test/base:context_utils'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_library(
  name = 'echo_interpreter_version_lib',
  sources = ['echo_interpreter_version.py'],
  dependencies = [],
  # Play with this to test interpreter selection in the pex machinery.
  compatibility = ['CPython>=2.6,<3']
)

python_tests(
  name = 'interpreter_selection_integration',
  sources = ['test_interpreter_selection_integration.py'],
  dependencies = [
    pants('src/python/pants/util:contextutil'),
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'python_run_integration',
  sources = ['test_python_run_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

python_tests(
  name = 'python_repl_integration',
  sources = ['test_python_repl_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)

# Used by interpreter_selection_integration.
python_binary(
  name = 'echo_interpreter_version_2.6',
  dependencies = [
    pants(':echo_interpreter_version_lib'),
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython>=2.6,<3']
)

# Used by interpreter_selection_integration.
python_binary(
  name = 'echo_interpreter_version_2.7',
  dependencies = [
    pants(':echo_interpreter_version_lib'),
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython>=2.7,<3']
)

# Useful for manual testing.
python_binary(
  name = 'echo_interpreter_version',
  dependencies = [
    pants(':echo_interpreter_version_lib'),
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
)

# Useful for manual testing.
python_binary(
  name = 'deliberately_conficting_compatibility',
  dependencies = [
    pants(':echo_interpreter_version_lib'),
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython<2.6']
)
