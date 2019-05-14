# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='inject_init',
  sources=['test_inject_init.py'],
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/engine:fs',
    'tests/python/pants_test/engine:util',
  ]
)

python_tests(
  name='python_test_runner',
  sources=['test_python_test_runner.py'],
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/engine/legacy:structs',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
