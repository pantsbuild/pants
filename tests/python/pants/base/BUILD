# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base-test',
  sources = ['context_utils.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('3rdparty/python:twitter.common.lang'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/reporting'),
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
    pants(':build_file'),
    pants(':build_invalidator'),
    pants(':build_root'),
    pants(':double_dag'),
    pants(':generator'),
    pants(':hash_utils'),
    pants(':parse_context'),
    pants(':revision'),
    pants(':run_info'),
  ]
)

python_tests(
  name = 'abbreviate_target_ids',
  sources = ['test_abbreviate_target_ids.py'],
  dependencies = [
    pants('src/python/pants/base:abbreviate_target_ids'),
  ]
)

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
  ]
)

python_tests(
  name = 'build_file',
  sources = ['test_build_file.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_file'),
  ]
)

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('src/python/pants/base:build_invalidator'),
  ]
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_root'),
  ]
)

python_tests(
  name = 'double_dag',
  sources = ['test_double_dag.py'],
  dependencies = [
    pants('src/python/pants/base:double_dag'),
    pants('src/python/pants/reporting'),
    pants('tests/python/pants/testutils'),
  ]
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
  dependencies = [
    pants('src/python/pants/base:generator'),
  ]
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
  dependencies = [
    pants('3rdparty/python:mox'),
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('src/python/pants/base:hash_utils'),
  ]
)

python_tests(
  name = 'parse_context',
  sources = ['test_parse_context.py'],
  dependencies = [
    pants('tests/python/pants:base-test'),
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
  ]
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
  dependencies = [
    pants('src/python/pants/base:revision'),
  ]
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('src/python/pants/base:run_info'),
  ]
)
