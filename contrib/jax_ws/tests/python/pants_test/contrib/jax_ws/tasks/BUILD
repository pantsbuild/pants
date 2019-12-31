# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_jax_ws_gen.py'],
  dependencies=[
    'contrib/jax_ws/src/python/pants/contrib/jax_ws/tasks',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['test_jax_ws_gen_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil:file_test_util',
    'contrib/jax_ws:wsdl_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=300,
)
