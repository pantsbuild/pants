# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# XXX this tests the code running the test, not the code under test!
python_tests(
  name = 'test_antlr_builder',
  sources = ['test_antlr_builder.py'],
  dependencies = [
    '3rdparty/python:antlr-3.1.3',
    'testprojects/src/antlr/pants/backend/python/test:csv',
    'testprojects/src/antlr/pants/backend/python/test:eval',
    'src/python/pants/backend/python:python_setup',
  ],
)

# XXX this tests the code running the test, not the code under test!
python_tests(
  name = 'test_thrift_namespace_packages',
  sources = ['test_thrift_namespace_packages.py'],
  dependencies = [
    'testprojects/src/thrift/org/pantsbuild/testing:duck-py',
    'testprojects/src/thrift/org/pantsbuild/testing:goose-py',
  ],
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
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'python_run_integration',
  sources = ['test_python_run_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'test_interpreter_cache',
  sources = ['test_interpreter_cache.py'],
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

# Used by interpreter_selection_integration.
python_binary(
  name = 'echo_interpreter_version_2.6',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython>=2.6,<2.7']
)

# Used by interpreter_selection_integration.
python_binary(
  name = 'echo_interpreter_version_2.7',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython>=2.7,<3']
)

# Useful for manual testing.
python_binary(
  name = 'echo_interpreter_version',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
)

# Useful for manual testing.
python_binary(
  name = 'deliberately_conficting_compatibility',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'pants_test.python.echo_interpreter_version',
  compatibility = ['CPython<2.6']
)

python_library(
  name = 'die_lib',
  sources = ['die.py'],
  dependencies = [],
  compatibility = ['CPython>=2.6,<3']
)

python_binary(
  name = 'die',
  dependencies = [
    ':die_lib',
  ],
  entry_point = 'pants_test.python.die',
)
