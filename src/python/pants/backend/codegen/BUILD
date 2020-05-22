# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  dependencies = [
    'src/python/pants/backend/codegen/protobuf/java',
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/codegen/thrift/python',
    'src/python/pants/backend/codegen/grpcio/python',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {"partially_type_checked"},
)
