# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':commands'),
  ]
)

python_test_suite(
  name = 'commands',
  dependencies = [
    pants(':test_goal'),
    pants(':test_setup_py'),
  ]
)

python_tests(
  name = 'test_goal',
  sources = [ 'test_goal.py' ],
  dependencies = [
    pants('src/python/pants/backend/jvm:plugin'),
    pants('src/python/pants/commands:goal'),
    pants('src/python/pants/goal:phase'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_tests(
  name = 'test_setup_py',
  sources = [ 'test_setup_py.py' ],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python:mock'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/python/commands:setup_py'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python:python_artifact'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test:base_test'),
  ]
)
