# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='pex',
  source='test_pex.py',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ]
)

python_tests(
  name='inject_init',
  source='test_inject_init.py',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/util:collections',
    'src/python/pants/testutil:test_base',
  ]
)

python_tests(
  name='python_test_runner',
  source='test_python_test_runner.py',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/build_graph',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:isolated_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/rules/core',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name='python_test_runner_integration',
  source='test_python_test_runner_integration.py',
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python/pants:dummies_directory',
  ],
  tags={'integration'},
  timeout = 90,
)

python_tests(
  name='python_fmt_integration',
  source='test_python_fmt_integration.py',
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:unicode_directory',
    'examples/src/python/example:hello_directory',
  ],
  tags={'integration'},
  timeout = 90,
)

