# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_*.py', '!test_exception_sink.py', '!test_*_integration.py'],
  dependencies = [
    '//:build_root',
  ],
)

python_tests(
  name='exception_sink',
  sources=['test_exception_sink.py'],
  tags=['platform_specific_behavior'],
  timeout=90,
)

python_integration_tests(
  name = 'exception_sink_integration',
  sources = ['test_exception_sink_integration.py'],
  dependencies = [
    'examples/src/python/example:hello_directory',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  uses_pants_run=True,
  tags = ['platform_specific_behavior'],
  # NB: This frequently times out, but due to hanging. So, we want to fail eagerly. See
  # https://github.com/pantsbuild/pants/issues/8127.
  timeout = 200,
)

python_integration_tests(
  name = 'exiter_integration',
  sources = ['test_exiter_integration.py'],
  dependencies = [
    'testprojects/src/python:unicode_directory',
  ],
  uses_pants_run=True,
  timeout = 120,
)
