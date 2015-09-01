# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='targets',
  dependencies=[
    ':jar_dependency',
    ':jvm_app',
    ':jvm_binary',
    ':jvm_target',
    ':unpacked_jars',
  ]
)

python_tests(
  name='jar_dependency',
  sources=['test_jar_dependency.py'],
  dependencies=[
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/base:address',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jar_library',
  sources=['test_jar_library.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:target',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jvm_app',
  sources=['test_jvm_app.py'],
  dependencies=[
    'src/python/pants/backend/core:wrapped_globs',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:address',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jvm_binary',
  sources=['test_jvm_binary.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:target',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jvm_target',
  sources=['test_jvm_target.py'],
  dependencies=[
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:jvm',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='unpacked_jars',
  sources=['test_unpacked_jars.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'tests/python/pants_test:base_test',
  ]
)
