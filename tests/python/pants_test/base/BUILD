# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_environment',
  sources = ['test_build_environment.py'],
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    '//:build_root',
  ],
)

python_tests(
  name = 'cmd_line_spec_parser',
  sources = ['test_cmd_line_spec_parser.py'],
)

python_tests(
  name = 'deprecated',
  sources = ['test_deprecated.py'],
)

python_tests(
  name = 'fingerprint_strategy',
  sources = ['test_fingerprint_strategy.py'],
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
)

python_tests(
  name = 'payload',
  sources = ['test_payload.py'],
)

python_tests(
  name = 'payload_field',
  sources = ['test_payload_field.py'],
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
)

python_tests(
  name = 'worker_pool',
  sources = ['test_worker_pool.py'],
)

python_tests(
  name = 'validation',
  sources = ['test_validation.py'],
)

python_tests(
  name='exception_sink',
  sources=['test_exception_sink.py'],
  tags=['platform_specific_behavior'],
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
