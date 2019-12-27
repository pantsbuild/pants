# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies = [
    'contrib/googlejavaformat/src/python/pants/contrib/googlejavaformat',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ],
  tags = {'partially_type_checked'},
)
