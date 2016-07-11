# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':antlr_gen',
    ':apache_thrift_gen',
    ':jaxb_gen',
    ':protobuf_gen',
    ':ragel_gen',
    ':simple_codegen_task',
    ':wire_gen',
  ],
)

python_library(
  name = 'common',
  sources = ['__init__.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ]
)

python_library(
  name = 'apache_thrift_gen',
  sources = ['apache_thrift_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':simple_codegen_task',
    'src/python/pants/backend/codegen/subsystems:thrift_defaults',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:thrift_util',
    'src/python/pants/option',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'antlr_gen',
  sources = ['antlr_gen.py'],
  dependencies = [
    ':simple_codegen_task',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/java:util',
    'src/python/pants/option:option',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'jaxb_gen',
  sources = ['jaxb_gen.py'],
  dependencies = [
    ':common',
    ':simple_codegen_task',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
  ],
)

python_library(
  name = 'protobuf_gen',
  sources = ['protobuf_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':simple_codegen_task',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'ragel_gen',
  sources = ['ragel_gen.py'],
  dependencies = [
    ':simple_codegen_task',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'simple_codegen_task',
  sources = ['simple_codegen_task.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'wire_gen',
  sources = ['wire_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':protobuf_gen',
    ':simple_codegen_task',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/util:memo',
  ],
)
