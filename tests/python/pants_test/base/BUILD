# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'context_utils',
  sources = ['context_utils.py'],
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/goal:context',
    'src/python/pants/option',
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
    ':address',
    ':build_configuration',
    ':build_environment',
    ':build_file',
    ':build_file_address_mapper',
    ':build_file_aliases',
    ':build_file_parser',
    ':build_invalidator',
    ':build_root',
    ':cmd_line_spec_parser',
    ':config',
    ':deprecated',
    ':extension_loader',
    ':fingerprint_strategy',
    ':generator',
    ':hash_utils',
    ':payload',
    ':payload_field',
    ':revision',
    ':run_info',
    ':source_root',
    ':target',
  ]
)

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    'src/python/pants/base:address',
    'src/python/pants/base:build_root',
    'tests/python/pants_test:base_test',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    'src/python/pants/base:address',
    'src/python/pants/base:build_configuration',
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
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

python_tests(
  name = 'build_file',
  sources = ['test_build_file.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/base:build_file',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'build_file_address_mapper',
  sources = ['test_build_file_address_mapper.py'],
  dependencies = [
    'tests/python/pants_test:base_test',
  ]
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
  name = 'lazy_source_mapper',
  sources = ['test_lazy_source_mapper.py'],
  dependencies = [
    'tests/python/pants_test:base_test',
    'src/python/pants/base:target',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/backend/jvm/targets:java',
  ]
)

python_tests(
  name = 'build_file_aliases',
  sources = ['test_build_file_aliases.py'],
  dependencies = [
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
  ]
)


python_tests(
  name = 'build_file_parser',
  sources = ['test_build_file_parser.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:target',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    'src/python/pants/base:build_invalidator',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
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
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:cmd_line_spec_parser',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'config',
  sources = ['test_config.py'],
  dependencies = [
    'src/python/pants/base:config',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'extension_loader',
  sources = ['test_extension_loader.py'],
  dependencies = [
    'src/python/pants/base:build_configuration',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:extension_loader',
    'src/python/pants/base:target',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
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
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
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
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'target',
  sources = ['test_target.py'],
  dependencies = [
    'src/python/pants/backend/core',
    'src/python/pants/base:address',
    'src/python/pants/base:build_file_aliases',
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
  name = 'source_root',
  sources = ['test_source_root.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:address',
    'src/python/pants/base:addressable',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target',
    ]
)

python_tests(
  name = 'test_spec_exclude_integration',
  sources = [ 'test_spec_exclude_integration.py' ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)
