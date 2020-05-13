# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/backend/project_info/tasks:all',
    'src/python/pants/goal:task_registrar',
    '3rdparty/python:dataclasses',
    'src/python/pants/backend/graph_info/subsystems',
    'src/python/pants/base:build_root',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:console',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:platform',
    'src/python/pants/engine:process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/util:objects',
  ],
  tags = {"type_checked"},
)

python_tests(
  name = "tests",
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies = [
    ':project_info',
    'src/python/pants/backend/codegen/protobuf',
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/targets',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/testutil:goal_rule_test_base',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"type_checked"},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
  tags = {'integration', 'type_checked'},
)
