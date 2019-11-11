# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name='filedeps',
  source='test_filedeps.py',
  dependencies=[
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/jvm/targets:all',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/rules/core',
    'src/python/pants/testutil:console_rule_test_base',
  ]
)

python_tests(
  name='filedeps_integration',
  source='test_filedeps_integration.py',
  dependencies=[
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
  tags={'integration'},
)

python_tests(
  name='test',
  source='test_test.py',
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/rules/core',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
  ]
)

python_tests(
  name='run',
  source='test_run.py',
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/rules/core',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:console_rule_test_base',
    'src/python/pants/testutil/engine:util',
  ]
)

python_tests(
  name='fmt_integration',
  source='test_fmt_integration.py',
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:dummies_directory',
  ],
  tags={'integration'},
)

