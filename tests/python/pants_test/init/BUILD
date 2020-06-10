# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  dependencies = [
    '3rdparty/python:dataclasses',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/base:exceptions',
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/fs',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/python',
    'src/python/pants/subsystem',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:interpreter_selection_utils',
    'src/python/pants/testutil:test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:logging',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'test_util',
  sources = ['test_util.py'],
  dependencies = [
    'src/python/pants/init:util',
    # 'src/python/pants/testutil:int-test-for-export'
  ]
)
