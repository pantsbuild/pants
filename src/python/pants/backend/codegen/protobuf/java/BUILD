# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/backend/codegen/protobuf/subsystems',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries',
    'src/python/pants/build_graph',
    'src/python/pants/engine:target',
    'src/python/pants/fs',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/task',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)
