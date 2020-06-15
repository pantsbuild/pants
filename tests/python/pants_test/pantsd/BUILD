# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'test_deps',
  dependencies = [
    'src/python/pants/testutil:test_base'
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:process_manager',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'watchman',
  sources = ['test_watchman.py'],
  coverage = ['pants.pantsd.watchman'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'watchman_client',
  sources = ['test_watchman_client.py'],
  coverage = ['pants.pantsd.watchman_client'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman_client'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'pants_daemon',
  sources = ['test_pants_daemon.py'],
  coverage = ['pants.pantsd.pants_daemon'],
  dependencies = [
    ':test_deps',
    'src/python/pants/bin',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'pants_daemon_core',
  sources = ['test_pants_daemon_core.py'],
  dependencies = [
    'src/python/pants/bin',
    'src/python/pants/pantsd/service:pants_service',
    'src/python/pants/pantsd:pants_daemon_core',
    'src/python/pants/testutil:test_base'
  ],
  tags = {"partially_type_checked"},
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
  tags = {'partially_type_checked'},
)

python_tests(
  name = 'pantsd_integration',
  sources = ['test_pantsd_integration.py'],
  dependencies = [
    ':pantsd_integration_test_base',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/python/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/src/java/org/pantsbuild/testproject:bundle_directory',
    'testprojects/src/python:bad_requirements_directory',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects/src/python:nested_runs_directory',
    'testprojects/src/python:print_env_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 900
)

python_tests(
  name = 'watchman_launcher',
  sources = ['test_watchman_launcher.py'],
  coverage = ['pants.pantsd.watchman_launcher'],
  dependencies = [
    'tests/python/pants_test/pantsd:test_deps',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/pantsd:watchman_launcher'
  ],
  tags = {"partially_type_checked"},
)
