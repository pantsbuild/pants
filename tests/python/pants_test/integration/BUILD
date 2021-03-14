# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_integration_tests(
  name = 'build_ignore_integration',
  sources = ['build_ignore_integration_test.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
  uses_pants_run=True,
  timeout = 240,
)

python_integration_tests(
  name = 'goal_rule_integration',
  sources = ['goal_rule_integration_test.py'],
  dependencies = [
    'testprojects/src/python:hello_directory',
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
    'testprojects/src/python:hello_directory',
  ],
  uses_pants_run=True,
  timeout = 240,
)

python_integration_tests(
  name = 'prelude_integration',
  sources = ['prelude_integration_test.py'],
  uses_pants_run=True,
  timeout = 180,
)

python_integration_tests(
  name = 'log_output_integration',
  sources = ['log_output_integration_test.py'],
  uses_pants_run=True,
  timeout = 180,
)

python_integration_tests(
  name = 'remote_cache_integration',
  sources = ['remote_cache_integration_test.py'],
  dependencies = [
    'testprojects/src/python:hello_directory',
  ],
  uses_pants_run=True,
  timeout = 180,
)


python_library()
