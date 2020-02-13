# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies=[
    '3rdparty/python:parameterized',
    '3rdparty/python:pex',
    '//:build_root',
    '//:pants_pex',
    'build-support/regexes',
    'contrib/python/src/python/pants/contrib/python/checks/tasks/checkstyle',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/python',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
  ],
  tags = {'partially_type_checked'},
)
