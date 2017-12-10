# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'test_deps',
  dependencies = [
    '3rdparty/python:mock',
    'tests/python/pants_test:base_test'
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/util:process_handler',
  ]
)

python_tests(
  name = 'watchman',
  sources = ['test_watchman.py'],
  coverage = ['pants.pantsd.watchman'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman'
  ]
)

python_tests(
  name = 'watchman_client',
  sources = ['test_watchman_client.py'],
  coverage = ['pants.pantsd.watchman_client'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman_client'
  ]
)

python_tests(
  name = 'pailgun_server',
  sources = ['test_pailgun_server.py'],
  coverage = ['pants.pantsd.pailgun_server'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:pailgun_server'
  ]
)

python_tests(
  name = 'pants_daemon',
  sources = ['test_pants_daemon.py'],
  coverage = ['pants.pantsd.pants_daemon'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'pantsd_integration',
  sources = ['test_pantsd_integration.py'],
  dependencies = [
    '3rdparty/python:futures',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/util:collections',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/testutils:process_test_util',
    '3rdparty/python:ansicolors'
  ],
  tags = {'integration'},
  timeout = 900
)

python_tests(
  name = 'watchman_launcher',
  sources = ['test_watchman_launcher.py'],
  coverage = ['pants.pantsd.watchman_launcher'],
  dependencies = [
    'tests/python/pants_test/pantsd:test_deps',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'src/python/pants/pantsd:watchman_launcher'
  ]
)
