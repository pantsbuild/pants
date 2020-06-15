# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  sources=['README.md'],
)

python_tests(
  name = 'tests',
  dependencies = [
    ':addresses',
    ':collection',
    ':console',
    ':fs',
    ':goal',
    ':platform',
    ':process',
    ':rules',
    ':selectors',
    ':target',
    'src/python/pants/base:project_tree',
    'src/python/pants/engine/internals/examples:fs_test',
    'src/python/pants/engine/internals/examples:parsers',
    'src/python/pants/engine/internals:build_files',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine/internals:scheduler',
    'src/python/pants/engine/internals:scheduler_test_base',
    'src/python/pants/option',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:enums',
  ],
)

python_library(
  name='addresses',
  sources=['addresses.py'],
  dependencies=[
    ':collection',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph:address',
  ],
  tags = {"type_checked"},
)

python_library(
  name='collection',
  sources=['collection.py'],
  dependencies=[
    'src/python/pants/util:ordered_set',
  ],
  tags = {'type_checked'},
)

python_library(
  name='console',
  sources=['console.py'],
  dependencies=[
    '3rdparty/python:ansicolors',
    ':rules',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/internals:scheduler',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='desktop',
  sources=['desktop.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':console',
    ':interactive_process',
    'src/python/pants/util:osutil',
    'src/python/pants/util:strutil',
  ],
  tags = {"type_checked"},
)

python_library(
  name='fs',
  sources=['fs.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':collection',
    ':rules',
    # 'src/python/pants/engine/internals:scheduler',  # dep cycle
    'src/python/pants/option',
    'src/python/pants/option:global_options',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ],
  tags = {'type_checked'},
)

python_library(
  name='goal',
  sources=['goal.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/cache',
    'src/python/pants/option',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/subsystem',
    'src/python/pants/util:meta',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='interactive_process',
  sources=['interactive_process.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':fs',
    ':rules',
    'src/python/pants/base:exception_sink',
    # 'src/python/pants/engine/internals:scheduler',  # dep cycle
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='platform',
  sources=['platform.py'],
  dependencies=[
    ':rules',
    'src/python/pants/util:memo',
    'src/python/pants/util:osutil',
  ],
  tags = {"type_checked"},
)

python_library(
  name='process',
  sources=['process.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':fs',
    ':platform',
    ':rules',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='rules',
  sources=['rules.py'],
  dependencies=[
    ':goal',
    ':selectors',
    ':unions',
    'src/python/pants/base:deprecated',
    'src/python/pants/option',
    'src/python/pants/util:collections',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='selectors',
  sources=['selectors.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:deprecated',
    'src/python/pants/util:meta',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='target',
  sources=['target.py'],
  dependencies=[
    ':addresses',
    ':collection',
    ':fs',
    ':rules',
    ':selectors',
    ':unions',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph:bundle',
    'src/python/pants/option:global_options',
    'src/python/pants/source',
    'src/python/pants/util:collections',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
    'src/python/pants/util:strutil',
  ],
  tags = {'type_checked'},
)

python_library(
  name='unions',
  sources=['unions.py'],
  dependencies=[
    'src/python/pants/util:frozendict',
    'src/python/pants/util:ordered_set',
    'src/python/pants/util:meta',
  ],
  tags = {'type_checked'},
)
