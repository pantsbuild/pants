# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/engine:console',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:enums',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='tests',
  dependencies=[
    ':rules',
    'src/python/pants/testutil:goal_rule_test_base',
  ],
  tags = {'partially_type_checked'},
)
