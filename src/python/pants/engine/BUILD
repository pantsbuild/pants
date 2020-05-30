# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  sources=['README.md'],
)

# TODO: Get rid of all these microtargets. The entire package should be one target,
# or be split into multiple packages.

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

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    ':selectors',
    ':target',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_library(
  name='addresses',
  sources=['addresses.py'],
  dependencies=[
    ':collection',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
  ],
  tags = {"type_checked"},
)

python_library(
  name='collection',
  sources=['collection.py'],
  tags = {'type_checked'},
)

python_library(
  name='console',
  sources=['console.py'],
  dependencies=[
    '3rdparty/python:ansicolors',
    ':rules',
    'src/python/pants/engine/internals:native',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='desktop',
  sources=['desktop.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':console',
    ':interactive_runner',
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
    'src/python/pants/option',
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
    'src/python/pants/subsystem',
    'src/python/pants/util:meta',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='interactive_runner',
  sources=['interactive_runner.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:exception_sink',
    ':fs',
    ':rules',
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
    'src/python/pants/option',
    'src/python/pants/util:collections',
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
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='target',
  sources=['target.py'],
  dependencies=[
    ':collection',
    ':rules',
    ':unions',
    '3rdparty/python:typing-extensions',
    'src/python/pants/util:collections',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
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
