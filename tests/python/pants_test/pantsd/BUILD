# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  dependencies = [
    'src/python/pants/testutil:test_base',
    'src/python/pants/pantsd:process_manager',
  ],
)

python_tests(
  name = 'pants_daemon',
  sources = ['test_pants_daemon.py'],
  dependencies = [
    'src/python/pants/testutil:test_base',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name = 'pants_daemon_core',
  sources = ['test_pants_daemon_core.py'],
  dependencies = [
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/pantsd:pants_daemon_core',
    'src/python/pants/testutil:test_base'
  ],
)

python_library(
  name = 'pantsd_integration_test_base',
  sources = ['pantsd_integration_test_base.py'],
  dependencies = [
    '3rdparty/python:ansicolors',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil:process_test_util',
    'src/python/pants/testutil:retry',
    'src/python/pants/util:collections',
  ],
)

python_tests(
  name = 'pantsd_integration',
  sources = ['test_pantsd_integration.py'],
  dependencies = [
    ':pantsd_integration_test_base',
    'examples/src/python/example:hello_directory',
    'testprojects/src/python:bad_requirements_directory',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects/src/python:print_env_directory',
  ],
  tags = ['integration'],
  timeout = 1020
)
