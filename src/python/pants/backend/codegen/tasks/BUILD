# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':apache_thrift_gen',
    ':antlr_gen',
    ':code_gen',
    ':protobuf_gen',
    ':ragel_gen',
    ':scrooge_gen',
    ':jaxb_gen',
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
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants(':code_gen'),
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants:thrift_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'antlr_gen',
  sources = ['antlr_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants(':code_gen'),
    pants(':common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'code_gen',
  sources = ['code_gen.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
  ],
)

python_library(
  name = 'jaxb_gen',
  sources = ['jaxb_gen.py'],
  dependencies = [
    pants(':code_gen'),
    pants(':common'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/java:distribution'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'protobuf_gen',
  sources = ['protobuf_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants(':code_gen'),
    pants(':common'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'ragel_gen',
  sources = ['ragel_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants(':code_gen'),
    pants(':common'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/java:distribution'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants:binary_util'),
  ],
)

python_library(
  name = 'scrooge_gen',
  sources = ['scrooge_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants:thrift_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)
