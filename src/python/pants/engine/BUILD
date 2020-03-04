# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  source='README.md',
)

# TODO: Get rid of all these microtargets. The entire package should be one target,
# or be split into multiple packages.

python_tests(
  name = 'tests',
  dependencies = [
    ':console',
    ':goal',
    ':rules',
    'src/python/pants/testutil/engine:util',
  ],
)

python_library(
  name = 'legacy_engine',
  sources = ['legacy_engine.py', 'round_engine.py', 'round_manager.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/goal',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='addressable',
  sources=['addressable.py'],
  dependencies=[
    ':objects',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='struct',
  sources=['struct.py'],
  dependencies=[
    ':addressable',
    ':objects',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='fs',
  sources=['fs.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':objects',
    ':rules',
    ':selectors',
    'src/python/pants/base:project_tree',
    'src/python/pants/option',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='goal',
  sources=['goal.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/cache',
    'src/python/pants/option',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='build_files',
  sources=['build_files.py'],
  dependencies=[
    ':addressable',
    ':fs',
    ':mapper',
    ':objects',
    ':selectors',
    ':struct',
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/util:collections',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:filtering',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='mapper',
  sources=['mapper.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':objects',
    ':parser',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='interactive_runner',
  sources=['interactive_runner.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:exception_sink',
    ':rules',
    ':platform',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='isolated_process',
  sources=['isolated_process.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':fs',
    ':rules',
    ':platform',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='nodes',
  sources=['nodes.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':addressable',
    ':fs',
    ':struct',
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='objects',
  sources=['objects.py'],
  tags = {'partially_type_checked'},
)

python_library(
  name='parser',
  sources=['parser.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':struct',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='platform',
  sources=['platform.py'],
  dependencies=[
    ':rules',
    'src/python/pants/util:collections',
    'src/python/pants/util:enums',
    'src/python/pants/util:memo',
    'src/python/pants/util:osutil',
  ],
  tags = {"type_checked"},
)

python_library(
  name='rules',
  sources=['rules.py'],
  dependencies=[
    ':goal',
    ':selectors',
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
  name='scheduler',
  sources=['scheduler.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':fs',
    ':isolated_process',
    ':native',
    ':nodes',
    ':objects',
    ':rules',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/rules/core:core',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='native',
  sources=['native.py'],
  dependencies=[
    ':native_engine_shared_library',
    ':fs',
    ':interactive_runner',
    ':isolated_process',
    ':selectors',
    '3rdparty/python:cffi',
    '3rdparty/python:setuptools',
    'src/python/pants/binaries',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)


python_library(
  name='console',
  sources=['console.py'],
  dependencies=[
    ':native',
    '3rdparty/python:ansicolors',
  ],
  tags = {'partially_type_checked'},
)

resources(
  name='native_engine_shared_library',
  sources=['native_engine.so']
)
