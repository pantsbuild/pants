# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:base_test',
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
  name = 'test_round_engine',
  sources = ['test_round_engine.py'],
  dependencies = [
    ':engine_test_base',
    'src/python/pants/engine:legacy_engine',
    'src/python/pants/task',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='addressable',
  sources=['test_addressable.py'],
  dependencies=[
    'src/python/pants/engine:addressable',
  ]
)

python_tests(
  name='fs',
  sources=['test_fs.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:nodes',
    'tests/python/pants_test/testutils:git_util',
  ]
)

python_tests(
  name='path_globs',
  sources=['test_path_globs.py'],
  dependencies=[
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:fs',
  ]
)

python_tests(
  name='struct',
  sources=['test_struct.py'],
  dependencies=[
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:struct',
  ]
)

python_tests(
  name='engine',
  sources=['test_engine.py'],
  dependencies=[
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/examples:planners',
    'src/python/pants/engine:engine',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:nodes',
    '3rdparty/python:mock',
  ]
)

python_tests(
  name='graph',
  sources=['test_graph.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'src/python/pants/engine:engine',
    'src/python/pants/engine:graph',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:storage',
    'src/python/pants/engine:struct',
    'tests/python/pants_test/engine/examples:parsers',
  ]
)

python_tests(
  name='mapper',
  sources=['test_mapper.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/examples:parsers',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:storage',
    'src/python/pants/engine:struct',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name='parsers',
  sources=['test_parsers.py'],
  dependencies=[
    'tests/python/pants_test/engine/examples:parsers',
    'src/python/pants/engine:objects',
  ]
)

python_tests(
  name='storage',
  sources=['test_storage.py'],
  dependencies=[
    'src/python/pants/engine:storage',
  ]
)

python_tests(
  name='scheduler',
  sources=['test_scheduler.py'],
  coverage=['pants.engine.nodes', 'pants.engine.scheduler'],
  dependencies=[
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/examples:planners',
    'src/python/pants/engine:engine',
    'src/python/pants/engine:scheduler',
  ]
)

python_tests(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
  dependencies=[
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/engine:engine',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:storage',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name='graph_validator',
  sources=['test_graph_validator.py'],
  coverage=['pants.engine.nodes', 'pants.engine.scheduler'],
  dependencies=[
    ':scheduler',
  ]
)
