# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'test_deps',
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:pytest',
    'tests/python/pants_test:base_test'
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:process_manager'
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
  name = 'daemon',
  sources = ['test_pants_daemon.py'],
  coverage = ['pants.pantsd.pants_daemon'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/util:contextutil'
  ]
)

python_tests(
  name = 'pantsd_integration',
  sources = ['test_pantsd_integration.py'],
  dependencies = [
    'src/python/pants/pantsd:process_manager',
    'tests/python/pants_test:int-test'
  ],
  tags = {'integration'}
)
