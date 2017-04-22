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
    'src/python/pants/backend/codegen/antlr/java',
    'src/python/pants/backend/codegen/jaxb',
    'src/python/pants/backend/codegen/protobuf/java',
    'src/python/pants/backend/codegen/ragel/java',
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/codegen/wire/java',
    'src/python/pants/base:deprecated',
  ],
)

python_library(
  name = 'python',
  sources = [
    'python_antlr_library.py',
    'python_thrift_library.py',
  ],
  dependencies = [
    # Note that this is part of a gnarly dependency chain:
    #  backend/python:thrift_builder ->
    #  src/python/pants/backend/codegen/thrift/python ->
    #  backend/python/targets
    # This isn't circular, but it's still bad that it crosses between backends and back again.
    # TODO: Clean this up. thrift_builder should almost certainly be in the codegen backend.
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/codegen/antlr/python',
    'src/python/pants/backend/codegen/thrift/python',
    'src/python/pants/base:deprecated',
  ],
)
