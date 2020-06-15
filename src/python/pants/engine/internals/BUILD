# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies=[
    ':build_files',
    ':core_abstractions',
    ':graph',
    ':options_parsing',
    ':native',
    ':scheduler',
    ':scheduler_test_base',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:project_tree',
    'src/python/pants/base:specs',
    'src/python/pants/engine/internals/examples:parsers',
    'src/python/pants/engine/internals/examples:graph_test',
    'src/python/pants/engine/internals/examples:mapper_test',
    'src/python/pants/engine/internals/examples:scheduler_inputs',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:logging',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"type_checked"},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'src/python/pants/testutil:int-test',
    'src/python/pants/util:contextutil',
  ],
  tags = {'integration', 'partially_type_checked'},
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
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph:address',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='build_files',
  sources=['build_files.py'],
  dependencies=[
    ':core_abstractions',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:project_tree',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/option',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    ':core_abstractions',
    '3rdparty/python:dataclasses',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source:filespec',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"type_checked"},
)

python_library(
  name='native',
  sources=['native.py'],
  dependencies=[
    ':native_engine_so',
    '3rdparty/python:setuptools',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:exiter',
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:interactive_process',
    'src/python/pants/engine:platform',
    'src/python/pants/engine:process',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:unions',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

resources(
  name='native_engine_so',
  sources=['native_engine.so'],
)

python_library(
  name='options_parsing',
  sources=['options_parsing.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/engine:rules',
    'src/python/pants/option',
    'src/python/pants/util:logging',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='scheduler',
  sources=['scheduler.py'],
  dependencies=[
    ':core_abstractions',
    ':native',
    '3rdparty/python:dataclasses',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:exception_sink',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:logging',
    'src/python/pants/util:ordered_set',
    'src/python/pants/util:strutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
  dependencies=[
    ':core_abstractions',
    ':scheduler',
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:fs',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)
