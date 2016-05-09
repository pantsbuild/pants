# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'apache_thrift_gen',
  sources = ['test_apache_thrift_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:apache_thrift_gen',
    'src/python/pants/backend/jvm/targets:java',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'antlr_gen',
  sources = ['test_antlr_gen.py'],
  dependencies = [
    '3rdparty/python:twitter.common.dirutil',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:antlr_gen',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
  ],
)

python_tests(
  name = 'antlr_integration',
  sources = ['test_antlr_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'jaxb_gen',
  sources = ['test_jaxb_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:jaxb_gen',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'protobuf_gen',
  sources = ['test_protobuf_gen.py'],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/backend/codegen/tasks:protobuf_gen',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'protobuf_integration',
  sources = ['test_protobuf_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'ragel_gen',
  sources = ['test_ragel_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:ragel_gen',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'simple_codegen_task',
  sources = ['test_simple_codegen_task.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:simple_codegen_task',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'wire_gen',
  sources = ['test_wire_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:wire_gen',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'wire_integration',
  sources = ['test_wire_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/testutils:file_test_util',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
