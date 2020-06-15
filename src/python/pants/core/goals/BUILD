# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_root',
    'src/python/pants/base:exiter',
    'src/python/pants/base:specs',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:console',
    'src/python/pants/engine:desktop',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:interactive_process',
    'src/python/pants/engine:process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option:global_options',
    'src/python/pants/util:contextutil',
  ],
  tags = {"type_checked"},
)

python_tests(
  name = "tests",
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    ':goals',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:console',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:interactive_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil:test_base',
    'src/python/pants/option:global_options',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    ':goals',
    'examples/src/python/example:hello_directory',
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:interactive_process',
    'src/python/pants/engine:rules',
    'src/python/pants/testutil:goal_rule_test_base',
    'src/python/pants/testutil:int-test',
    '//:isort_cfg',
    'examples:isort_cfg',
    'contrib:isort_cfg',
  ],
  tags = {'integration', 'partially_type_checked'},
)
