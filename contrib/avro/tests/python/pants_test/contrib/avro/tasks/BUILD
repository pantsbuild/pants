# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='avro_java_gen',
  sources=['test_avro_gen.py'],
  dependencies=[
    'contrib/avro/src/python/pants/contrib/avro/targets',
    'contrib/avro/src/python/pants/contrib/avro/tasks',
    'src/python/pants/build_graph:build_graph',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='avro_java_gen_integration',
  sources=['test_avro_gen_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/avro:avro_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
)
