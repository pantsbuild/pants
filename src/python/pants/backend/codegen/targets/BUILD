# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'java',
  sources = [
    'java_antlr_library.py',
    'java_protobuf_library.py',
    'java_thrift_library.py',
    'java_ragel_library.py',
    'java_wire_library.py',
    'jaxb_library.py',
  ],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:validation',
  ],
)

python_library(
  name = 'python',
  sources = [
    'python_antlr_library.py',
    'python_thrift_library.py',
  ],
  dependencies = [
    'src/python/pants/backend/python/targets:python',
  ],
)
