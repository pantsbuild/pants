# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'legacy_engine',
  sources = ['test_legacy_engine.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/engine:legacy_engine',
    'src/python/pants/testutil/base:context_utils',
    'src/python/pants/testutil/engine:engine_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='round_engine',
  sources=['test_round_engine.py'],
  dependencies = [
    'src/python/pants/engine:legacy_engine',
    'src/python/pants/task',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:engine_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='addressable',
  sources=['test_addressable.py'],
  dependencies=[
    'src/python/pants/engine:addressable',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='fs',
  sources=['test_fs.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:nodes',
    'src/python/pants/testutil:test_base',
    'tests/python/pants_test/engine/examples:fs_test',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='isolated_process',
  sources=['test_isolated_process.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:isolated_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
    'tests/python/pants_test/engine/examples:fs_test',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='selectors',
  sources=['test_selectors.py'],
  dependencies=[
    'src/python/pants/engine:selectors',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='struct',
  sources=['test_struct.py'],
  dependencies=[
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:struct',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  sources=['test_engine.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':scheduler_test_base',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'src/python/pants/engine:nodes',
    'src/python/pants/engine:scheduler',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/reporting',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='build_files',
  sources=['test_build_files.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:struct',
    'src/python/pants/util:objects',
    'tests/python/pants_test/engine/examples:graph_test',
    'tests/python/pants_test/engine/examples:parsers',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='mapper',
  sources=['test_mapper.py'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:struct',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/engine/examples:mapper_test',
    'tests/python/pants_test/engine/examples:parsers',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='parsers',
  sources=['test_parsers.py'],
  dependencies=[
    'tests/python/pants_test/engine/examples:parsers',
    'src/python/pants/engine:objects',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='rules',
  sources=['test_rules.py'],
  coverage=['pants.engine.rules'],
  dependencies=[
    ':scheduler_test_base',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:console',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'tests/python/pants_test/engine/examples:parsers',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='scheduler',
  sources=['test_scheduler.py'],
  coverage=['pants.engine.nodes', 'pants.engine.scheduler'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/build_graph',
    'src/python/pants/engine:scheduler',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='scheduler_integration',
  sources=['test_scheduler_integration.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
  tags={'integration', 'partially_type_checked'},
)

python_library(
  name='scheduler_test_base',
  sources=['scheduler_test_base.py'],
  dependencies=[
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='objects',
  sources=['test_objects.py'],
  dependencies=[
    'src/python/pants/engine:objects',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)
