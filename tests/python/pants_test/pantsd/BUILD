# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
)

python_tests(
  name = 'pants_daemon',
  sources = ['test_pants_daemon.py'],
)

python_tests(
  name = 'pants_daemon_core',
  sources = ['test_pants_daemon_core.py'],
)

python_library(
  name = 'pantsd_integration_test_base',
  sources = ['pantsd_integration_test_base.py'],
)

python_integration_tests(
  name = 'pantsd_integration',
  dependencies = [
    'examples/src/python/example:hello_directory',
    'testprojects/src/python:bad_requirements_directory',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects/src/python:nested_runs_directory',
    'testprojects/src/python:print_env_directory',
  ],
  timeout = 1020
)
