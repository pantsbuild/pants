# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_rpmbuild_task.py'],
  dependencies=[
    'contrib/rpmbuild/src/python/pants/contrib/rpmbuild/targets',
    'contrib/rpmbuild/src/python/pants/contrib/rpmbuild/tasks',
    'src/python/pants/build_graph:build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='rpmbuild_integration',
  sources=['test_rpmbuild_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

rpm_package(
  name='pants-testpkg',
  spec='pants-testpkg.spec',
  defines={
    'version': '1.0',
  },
  sources=['do-nothing.sh']
)
