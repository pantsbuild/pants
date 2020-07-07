# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies=[
    'src/python/pants/engine/internals/examples:parsers',
    'src/python/pants/engine/internals/examples:graph_test',
    'src/python/pants/engine/internals/examples:mapper_test',
    'src/python/pants/engine/internals/examples:scheduler_inputs',
  ],
)

python_integration_tests(
  name='integration',
  dependencies=[
    'examples/src/python/example:hello_directory',
  ],
)

python_library(
  name='core_abstractions',
  sources=[
    'addressable.py',
    'mapper.py',
    'nodes.py',
    'objects.py',
    'parser.py',
    'struct.py'
  ],
)

python_library(
  name='build_files',
  sources=['build_files.py'],
)

python_library(
  name='graph',
  sources=['graph.py'],
)

python_library(
  name='native',
  sources=['native.py'],
  dependencies=[
    ':native_engine',
  ],
)

resources(
  name='native_engine',
  sources=[
    'native_engine.so',
    'native_engine.so.metadata',
  ],
)

python_library(
  name='options_parsing',
  sources=['options_parsing.py'],
)

python_library(
  name='scheduler',
  sources=['scheduler.py'],
)

python_library(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
)
