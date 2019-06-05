# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='inject_init',
  source='test_inject_init.py',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/util:collections',
    'tests/python/pants_test:test_base',
  ]
)

python_tests(
  name='python_test_runner_integration',
  source='test_python_test_runner_integration.py',
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='resolve_requirements',
  source='test_resolve_requirements.py',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
