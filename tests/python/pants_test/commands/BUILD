# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'all',
  dependencies = [
    ':commands',
  ]
)

python_test_suite(
  name = 'commands',
  dependencies = [
    ':test_goal',
    ':test_setup_py',
  ]
)

python_test_suite(
  name = 'integration',
  dependencies = [
    ':test_spec_exclude_integration',
  ]
)

python_tests(
  name = 'test_goal',
  sources = [ 'test_goal.py' ],
  dependencies = [
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/commands:goal_runner',
    'src/python/pants/goal',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'test_setup_py',
  sources = [ 'test_setup_py.py' ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:mock',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/python/commands:setup_py',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'test_spec_exclude_integration',
  sources = [ 'test_spec_exclude_integration.py' ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)
