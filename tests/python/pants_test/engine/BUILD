# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/binaries',
    'src/python/pants/engine:addressable',
    'src/python/pants/engine:native',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:struct',
    'src/python/pants/util:objects',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_library(
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:test_base',
  ]
)

python_tests(
  name = 'test_legacy_engine',
  sources = ['test_legacy_engine.py'],
  dependencies = [
    ':engine_test_base',
    'src/python/pants/base:exceptions',
    'src/python/pants/engine:legacy_engine',
    'tests/python/pants_test/base:context_utils',
  ],
)

python_tests(
  name='test_round_engine',
  sources=['test_round_engine.py'],
  dependencies = [
    ':engine_test_base',
    'src/python/pants/engine:legacy_engine',
    'src/python/pants/task',
    'tests/python/pants_test:test_base',
  ],
)

python_tests(
  name='addressable',
  sources=['test_addressable.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/engine:addressable',
    'src/python/pants/util:objects',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='fs',
  sources=['test_fs.py'],
  dependencies=[
    ':scheduler_test_base',
    '3rdparty/python:future',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:nodes',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine/examples:fs_test',
  ]
)

python_tests(
  name='graph',
  sources=['test_graph.py'],
  coverage=['pants.engine.graph'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/build_graph',
    'src/python/pants/engine:scheduler',
    'tests/python/pants_test/engine/examples:planners',
  ]
)

python_tests(
  name='isolated_process',
  sources=['test_isolated_process.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:isolated_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine/examples:fs_test',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
  ]
)

python_tests(
  name='selectors',
  sources=['test_selectors.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/engine:selectors',
  ]
)

python_tests(
  name='struct',
  sources=['test_struct.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:struct',
  ]
)

python_tests(
  sources=['test_engine.py'],
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:mock',
    ':scheduler_test_base',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'src/python/pants/engine:nodes',
    'src/python/pants/engine:scheduler',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/engine/examples:planners',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
    'tests/python/pants_test/engine:util',
  ]
)

python_tests(
  name='build_files',
  sources=['test_build_files.py'],
  dependencies=[
    '3rdparty/python:future',
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:struct',
    'src/python/pants/util:objects',
    'tests/python/pants_test/engine/examples:graph_test',
    'tests/python/pants_test/engine/examples:parsers',
  ]
)

python_tests(
  name='mapper',
  sources=['test_mapper.py'],
  dependencies=[
    '3rdparty/python:future',
    ':scheduler_test_base',
    ':util',
    'src/python/pants/build_graph',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:struct',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/engine/examples:mapper_test',
    'tests/python/pants_test/engine/examples:parsers',
  ]
)

python_tests(
  name='parsers',
  sources=['test_parsers.py'],
  dependencies=[
    '3rdparty/python:future',
    'tests/python/pants_test/engine/examples:parsers',
    'src/python/pants/engine:objects',
  ]
)

python_tests(
  name='rules',
  sources=['test_rules.py'],
  coverage=['pants.engine.rules'],
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':util',
    ':scheduler_test_base',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:objects',
    'tests/python/pants_test/engine/examples:parsers',
    'tests/python/pants_test/engine/examples:planners',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
  name='scheduler',
  sources=['test_scheduler.py'],
  coverage=['pants.engine.nodes', 'pants.engine.scheduler'],
  dependencies=[
    '3rdparty/python:future',
    ':util',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'src/python/pants/engine:scheduler',
    'tests/python/pants_test/engine/examples:planners',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
  ]
)

python_tests(
  name='scheduler_integration',
  sources=['test_scheduler_integration.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
  dependencies=[
    '3rdparty/python:future',
    ':util',
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/util:dirutil',
  ]
)
