# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'context_utils',
  sources = ['context_utils.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:workunit',
    'src/python/pants/build_graph',
    'src/python/pants/goal:context',
    'tests/python/pants_test/option/util',
  ]
)

target(
  name = 'all',
  dependencies = [
    ':base',
  ]
)

target(
  name = 'integration',
  dependencies = [
    ':test_spec_exclude_integration',
  ]
)

target(
  name = 'base',
  dependencies = [
    ':build_environment',
    ':build_root',
    ':cmd_line_spec_parser',
    ':deprecated',
    ':filesystem_build_file',
    ':fingerprint_strategy',
    ':generator',
    ':hash_utils',
    ':payload',
    ':payload_field',
    ':revision',
    ':run_info',
    ':validation',
    ':worker_pool',
  ]
)

python_tests(
  name = 'build_environment',
  sources = ['test_build_environment.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:fileutil',
  ]
)

python_library(
  name = 'build_file_test_base',
  sources = ['build_file_test_base.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'filesystem_build_file',
  sources = ['test_filesystem_build_file.py'],
  dependencies = [
    ':build_file_test_base',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/base:build_file',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'build_graph_cache',
  sources = ['test_build_graph_cache.py'],
  dependencies = [
    'src/python/pants/base:address',
    'src/python/pants/base:build_graph_cache',
    'tests/python/pants_test:base_test'
  ],
)

python_tests(
  name = 'deprecated',
  sources = ['test_deprecated.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants:version',
  ]
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    'src/python/pants/base:build_root',
    'tests/python/pants_test:base_test',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'cmd_line_spec_parser',
  sources = ['test_cmd_line_spec_parser.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'fingerprint_strategy',
  sources = ['test_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/base:fingerprint_strategy',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
  dependencies = [
    'src/python/pants/base:generator',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
  dependencies = [
    '3rdparty/python:mox',
    'src/python/pants/base:hash_utils',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'payload',
  sources = ['test_payload.py'],
  dependencies = [
    'src/python/pants/backend/core',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'payload_field',
  sources = ['test_payload_field.py'],
  dependencies = [
    'src/python/pants/backend/core',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:payload_field',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
  dependencies = [
    'src/python/pants/base:run_info',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'scm_build_file',
  sources = ['test_scm_build_file.py'],
  dependencies = [
    ':build_file_test_base',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:scm_build_file',
    'src/python/pants/scm:git',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'test_spec_exclude_integration',
  sources = [ 'test_spec_exclude_integration.py' ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'worker_pool',
  sources = ['test_worker_pool.py'],
  dependencies = [
    'src/python/pants/base:worker_pool',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'validation',
  sources = ['test_validation.py'],
  dependencies = [
    'src/python/pants/base:validation',
  ]
)
