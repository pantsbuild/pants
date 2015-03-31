# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'tasks',
  dependencies = [
    ':antlr_gen',
    ':jaxb_gen',
    ':protobuf_gen',
    ':protobuf_parse',
    ':ragel_gen',
    ':wire_gen',
  ],
)

python_tests(
  name = 'antlr_gen',
  sources = ['test_antlr_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:antlr_gen',
    'tests/python/pants_test/tasks:base',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
  ],
)

python_tests(
  name = 'jaxb_gen',
  sources = ['test_jaxb_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:jaxb_gen',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:base',
  ],
)

python_tests(
  name = 'protobuf_gen',
  sources = ['test_protobuf_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:protobuf_gen',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'protobuf_parse',
  sources = ['test_protobuf_parse.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:protobuf_parse',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:base',
  ],
)

python_tests(
  name = 'ragel_gen',
  sources = ['test_ragel_gen.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:ragel_gen',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:context',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:task_test_base',
    'tests/python/pants_test/tasks:base',
  ],
)

python_tests(
  name = 'wire_gen',
  sources = ['test_wire_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/codegen/tasks:wire_gen',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/base:source_root',
    'src/python/pants/base:validation',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:task_test_base',
  ],
)
