# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_integration_tests(
  name = 'build_ignore_integration',
  sources = ['build_ignore_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
  uses_pants_run=True,
)

python_integration_tests(
  name = 'changed_integration',
  sources = ['changed_integration_test.py'],
  dependencies = [
    '//:gitignore',
    'testprojects/src/python:python_targets_directory',
    'testprojects/src/python:sources_directory',
  ],
  uses_pants_run=True,
  timeout = 600,
)

python_integration_tests(
  name = 'filesystem_specs_integration',
  sources = ['filesystem_specs_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python:owners_integration_target',
  ],
  uses_pants_run=True,
  timeout = 120,
)

python_integration_tests(
  name = 'goal_rule_integration',
  sources = ['goal_rule_integration_test.py'],
  dependencies = [
    'examples/src/python/example:hello_directory',
    'testprojects/tests/python/pants:dummies_directory',
  ],
  uses_pants_run=True,
  timeout = 330,
)

python_integration_tests(
  name='graph_integration',
  sources=['graph_integration_test.py'],
  dependencies=[
    'testprojects/src/python:no_build_file_directory',
    'testprojects/src/python:sources_directory',
  ],
  uses_pants_run=True,
  timeout = 180,
)

python_integration_tests(
  name = 'list_integration',
  sources = ['list_integration_test.py'],
  dependencies = [
    'testprojects/tests/python/pants:build_parsing_directory',
  ],
  uses_pants_run=True,
  timeout = 180,
)

python_integration_tests(
  name = 'prelude_integration',
  sources = ['test_prelude_integration.py'],
  uses_pants_run=True,
)
