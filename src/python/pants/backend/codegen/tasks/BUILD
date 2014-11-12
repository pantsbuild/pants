# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':apache_thrift_gen',
    ':antlr_gen',
    ':code_gen',
    ':protobuf_gen',
    ':protobuf_parse',
    ':ragel_gen',
    ':scrooge_gen',
    ':thrift_linter',
    ':jaxb_gen',
    ':wire_gen',
  ],
)

python_library(
  name = 'common',
  sources = ['__init__.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:exceptions',
  ]
)

python_library(
  name = 'apache_thrift_gen',
  sources = ['apache_thrift_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.log',
    ':code_gen',
    ':common',
    'src/python/pants/base:build_environment',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants:thrift_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'antlr_gen',
  sources = ['antlr_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':code_gen',
    ':common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'code_gen',
  sources = ['code_gen.py'],
  dependencies = [
    ':common',
    'src/python/pants/base:address_lookup_error',
    'src/python/pants/base:build_environment',
  ],
)

python_library(
  name = 'jaxb_gen',
  sources = ['jaxb_gen.py'],
  dependencies = [
    ':code_gen',
    ':common',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:source_root',
    'src/python/pants/java:distribution',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'protobuf_gen',
  sources = ['protobuf_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.log',
    ':code_gen',
    ':common',
    ':protobuf_parse',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants:binary_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'protobuf_parse',
  sources = ['protobuf_parse.py'],
  dependencies = [
    'src/python/pants/util:strutil',
  ]
)

python_library(
  name = 'ragel_gen',
  sources = ['ragel_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    ':code_gen',
    ':common',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:source_root',
    'src/python/pants/java:distribution',
    'src/python/pants/base:exceptions',
    'src/python/pants:binary_util',
  ],
)

python_library(
  name = 'scrooge_gen',
  sources = ['scrooge_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':common',
    'src/python/pants/base:build_environment',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants:thrift_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'thrift_linter',
  sources = ['thrift_linter.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':common',
    'src/python/pants/base:build_environment',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants:thrift_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'wire_gen',
  sources = ['wire_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':code_gen',
    ':protobuf_gen',
    ':protobuf_parse',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/base:address',
    'src/python/pants/base:address_lookup_error',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/java:util',
    'src/python/pants/util:dirutil',
  ],
)
