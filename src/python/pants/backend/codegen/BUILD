# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/codegen/tasks:antlr_gen',
    'src/python/pants/backend/codegen/tasks:apache_thrift_gen',
    'src/python/pants/backend/codegen/tasks:jaxb_gen',
    'src/python/pants/backend/codegen/tasks:protobuf_gen',
    'src/python/pants/backend/codegen/tasks:ragel_gen',
    'src/python/pants/backend/codegen/tasks:wire_gen',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
)
