# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_environment',
  sources = ['test_build_environment.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
  ],
  tags = {"type_checked"},
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    '//:build_root',
    'src/python/pants/base:build_root',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'exclude_target_regexp_integration',
  sources = [ 'test_exclude_target_regexp_integration.py' ],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:phrases_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 850,
)

python_tests(
  name = 'cmd_line_spec_parser',
  sources = ['test_cmd_line_spec_parser.py'],
  dependencies = [
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'deprecated',
  sources = ['test_deprecated.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/util:collections',
    'src/python/pants:version',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'filesystem_build_file',
  sources = ['test_filesystem_build_file.py'],
  dependencies = [
    '3rdparty/python:pathspec',
    'src/python/pants/base:build_file',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'fingerprint_strategy',
  sources = ['test_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
  dependencies = [
    'src/python/pants/base:generator',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
  dependencies = [
    'src/python/pants/base:hash_utils',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'payload',
  sources = ['test_payload.py'],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'payload_field',
  sources = ['test_payload_field.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/base:payload_field',
    'src/python/pants/python',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
  dependencies = [
    'src/python/pants/base:run_info',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'worker_pool',
  sources = ['test_worker_pool.py'],
  dependencies = [
    'src/python/pants/base:worker_pool',
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'validation',
  sources = ['test_validation.py'],
  dependencies = [
    'src/python/pants/base:validation',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'exception_sink',
  sources = ['test_exception_sink.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:enums',
    'src/python/pants/util:osutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/option',
  ],
  tags={'platform_specific_behavior', 'partially_type_checked'},
)

python_tests(
  name = 'exception_sink_integration',
  sources = ['test_exception_sink_integration.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/testutil:int-test',
    'src/python/pants/util:osutil',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
    'tests/python/pants_test/pantsd:pantsd_integration_test_base',
  ],
  tags = {'platform_specific_behavior', 'integration', 'partially_type_checked'},
  # NB: This frequently times out, but due to hanging. So, we want to fail eagerly. See
  # https://github.com/pantsbuild/pants/issues/8127.
  timeout = 200,
)

python_tests(
  name = 'exiter_integration',
  sources = [ 'test_exiter_integration.py' ],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:unicode_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 250,
)
