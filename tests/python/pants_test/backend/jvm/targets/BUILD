# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='credentials',
  sources=['test_credentials.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jar_dependency',
  sources=['test_jar_dependency.py'],
  dependencies=[
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:scala',
  ]
)

python_tests(
  name = 'jar_dependency_integration',
  sources = ['test_jar_dependency_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='jar_library',
  sources=['test_jar_library.py'],
  dependencies=[
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='junit_tests',
  sources=['test_junit_tests.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:junit',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_tests(
  name='jvm_app',
  sources=['test_jvm_app.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:parse_context',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jvm_binary',
  sources=['test_jvm_binary.py'],
  dependencies=[
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='jvm_target',
  sources=['test_jvm_target.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='unpacked_jars',
  sources=['test_unpacked_jars.py'],
  dependencies=[
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'tests/python/pants_test:base_test',
  ]
)
