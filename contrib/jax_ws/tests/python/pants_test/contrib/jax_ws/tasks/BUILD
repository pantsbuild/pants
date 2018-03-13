# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_jax_ws_gen.py'],
  dependencies=[
    'contrib/jax_ws/src/python/pants/contrib/jax_ws/tasks',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='integration',
  sources=['test_jax_ws_gen_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=300,
)
