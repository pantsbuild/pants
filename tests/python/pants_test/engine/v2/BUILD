# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='addressable',
  sources=['test_addressable.py'],
  dependencies=[
    'src/python/pants/engine/v2:addressable',
  ]
)

python_tests(
  name='fs',
  sources=['test_fs.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/engine/v2:fs',
    'src/python/pants/engine/v2:nodes',
    'tests/python/pants_test/testutils:git_util',
  ]
)

python_tests(
  name='path_globs',
  sources=['test_path_globs.py'],
  dependencies=[
    'src/python/pants/engine/v2:fs',
  ]
)

python_tests(
  name='struct',
  sources=['test_struct.py'],
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/v2:objects',
    'src/python/pants/engine/v2:struct',
  ]
)

python_tests(
  name='engine',
  sources=['test_engine.py'],
  dependencies=[
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/v2/examples:planners',
    'src/python/pants/engine/v2:engine',
    'src/python/pants/engine/v2:scheduler',
  ]
)

python_tests(
  name='graph',
  sources=['test_graph.py'],
  dependencies=[
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/v2/examples:parsers',
    'src/python/pants/engine/v2:graph',
    'src/python/pants/engine/v2:mapper',
    'src/python/pants/engine/v2:parser',
    'src/python/pants/engine/v2:storage',
    'src/python/pants/engine/v2:struct',
  ]
)

python_tests(
  name='mapper',
  sources=['test_mapper.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/v2/examples:parsers',
    'src/python/pants/engine/v2:mapper',
    'src/python/pants/engine/v2:storage',
    'src/python/pants/engine/v2:struct',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name='parsers',
  sources=['test_parsers.py'],
  dependencies=[
    'tests/python/pants_test/engine/v2/examples:parsers',
    'src/python/pants/engine/v2:objects',
  ]
)

python_tests(
  name='storage',
  sources=['test_storage.py'],
  dependencies=[
    'src/python/pants/engine/v2:storage',
  ]
)

python_tests(
  name='scheduler',
  sources=['test_scheduler.py'],
  coverage=['pants.engine.v2.nodes', 'pants.engine.v2.scheduler'],
  dependencies=[
    'src/python/pants/build_graph',
    'tests/python/pants_test/engine/v2/examples:planners',
    'src/python/pants/engine/v2:engine',
    'src/python/pants/engine/v2:scheduler',
  ]
)

python_tests(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
  dependencies=[
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/engine/v2:fs',
    'src/python/pants/engine/v2:parser',
    'src/python/pants/engine/v2:scheduler',
    'src/python/pants/engine/v2:storage',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name='graph_validator',
  sources=['test_graph_validator.py'],
  coverage=['pants.engine.v2.nodes', 'pants.engine.v2.scheduler'],
  dependencies=[
    ':scheduler',
  ]
)
