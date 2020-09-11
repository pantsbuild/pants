# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='java_thrift_library_fingerprint_strategy',
  sources=['test_java_thrift_library_fingerprint_strategy.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:java_thrift_library_fingerprint_strategy',
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='scrooge_gen',
  sources=['test_scrooge_gen.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:scrooge_gen',
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal:context',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:ordered_set',
    'src/python/pants/testutil/jvm:nailgun_task_test_base'
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='scrooge_gen_integration',
  sources=['test_scrooge_gen_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/scrooge:scala_tests_directory',
    'contrib/scrooge:thrift_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=600,
)

python_tests(
  name='thrift_linter_integration',
  sources=['test_thrift_linter_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/scrooge:thrift_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=400,
)

python_tests(
  name='thrift_linter',
  sources=['test_thrift_linter.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_linter',
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_util',
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil:mock_logger',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='thrift_util',
  sources=['test_thrift_util.py'],
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks:thrift_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)
