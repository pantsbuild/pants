# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'context_utils',
  sources = ['context_utils.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':base'),
  ],
)

python_test_suite(
  name = 'base',
  dependencies = [
    pants(':abbreviate_target_ids'),
    pants(':address'),
    pants(':build_configuration'),
    pants(':build_file'),
    pants(':build_file_aliases'),
    pants(':build_file_parser'),
    pants(':build_invalidator'),
    pants(':build_root'),
    pants(':cmd_line_spec_parser'),
    pants(':dev_backend_loader'),
    pants(':double_dag'),
    pants(':generator'),
    pants(':hash_utils'),
    pants(':payload'),
    pants(':revision'),
    pants(':run_info'),
  ]
)

python_tests(
  name = 'abbreviate_target_ids',
  sources = ['test_abbreviate_target_ids.py'],
  dependencies = [
    pants('src/python/pants/base:abbreviate_target_ids'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_root'),
    pants('tests/python/pants_test:base_test'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_configuration'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'build_file',
  sources = ['test_build_file.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file'),
    pants('tests/python/pants_test:base_test'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'build_file_aliases',
  sources = ['test_build_file_aliases.py'],
  dependencies = [
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:target'),
  ]
)


python_tests(
  name = 'build_file_parser',
  sources = ['test_build_file_parser.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('tests/python/pants_test:base_test'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:build_invalidator'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:build_root'),
    pants('tests/python/pants_test:base_test'),
    pants('src/python/pants/util:dirutil'),
  ]
)

python_tests(
  name = 'cmd_line_spec_parser',
  sources = ['test_cmd_line_spec_parser.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:cmd_line_spec_parser'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'dev_backend_loader',
  sources = ['test_dev_backend_loader.py'],
  dependencies = [
    pants('src/python/pants/base:build_configuration'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:dev_backend_loader'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/goal:phase'),
  ]
)

python_tests(
  name = 'double_dag',
  sources = ['test_double_dag.py'],
  dependencies = [
    pants('src/python/pants/base:double_dag'),
    pants('src/python/pants/reporting'),
    pants('tests/python/pants_test:base_test'),
    pants('tests/python/pants_test/testutils'),
  ]
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
  dependencies = [
    pants('src/python/pants/base:generator'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
  dependencies = [
    pants('3rdparty/python:mox'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:hash_utils'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'payload',
  sources = ['test_payload.py'],
  dependencies = [
    pants('src/python/pants/backend/core'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:payload'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
  dependencies = [
    pants('src/python/pants/base:revision'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:run_info'),
    pants('tests/python/pants_test:base_test'),
  ]
)
