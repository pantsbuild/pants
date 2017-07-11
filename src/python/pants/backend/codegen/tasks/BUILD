# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
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
  name = 'antlr_gen',
  sources = ['antlr_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/antlr/java',
  ],
)

python_library(
  name = 'apache_thrift_gen',
  sources = ['apache_thrift_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/thrift/java',
  ],
)

python_library(
  name = 'jaxb_gen',
  sources = ['jaxb_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/jaxb',
  ],
)

python_library(
  name = 'protobuf_gen',
  sources = ['protobuf_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/protobuf/java',
  ],
)

python_library(
  name = 'ragel_gen',
  sources = ['ragel_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/ragel/java',
  ],
)

python_library(
  name = 'simple_codegen_task',
  sources = ['simple_codegen_task.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'wire_gen',
  sources = ['wire_gen.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/backend/codegen/wire/java',
  ],
)
