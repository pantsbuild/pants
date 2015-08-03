# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':java_thrift_library_fingerprint_strategy',
    ':scrooge_gen',
    ':thrift_linter_integration',
    ':thrift_util',
  ],
)

python_tests(
  name='java_thrift_library_fingerprint_strategy',
  sources=['test_java_thrift_library_fingerprint_strategy.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:java_thrift_library_fingerprint_strategy',
    'src/python/pants/backend/codegen/subsystems:thrift_defaults',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name='scrooge_gen',
  sources=['test_scrooge_gen.py'],
  dependencies=[
    '3rdparty/python:mock',
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:scrooge_gen',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'src/python/pants/goal:context',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='thrift_linter_integration',
  sources=['test_thrift_linter_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name='thrift_util',
  sources=['test_thrift_util.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ]
)
