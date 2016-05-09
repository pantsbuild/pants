# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='java_thrift_library_fingerprint_strategy',
  sources=['test_java_thrift_library_fingerprint_strategy.py'],
  dependencies = [
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:java_thrift_library_fingerprint_strategy',
    'src/python/pants/backend/codegen/subsystems:thrift_defaults',
    'src/python/pants/backend/codegen/targets:java',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='scrooge_gen',
  sources=['test_scrooge_gen.py'],
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:twitter.common.collections',
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:scrooge_gen',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal:context',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='thrift_linter_integration',
  sources=['test_thrift_linter_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='thrift_linter',
  sources=['test_thrift_linter.py'],
  dependencies = [
    '3rdparty/python:mock',
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_linter',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='thrift_util',
  sources=['test_thrift_util.py'],
  dependencies = [
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)
