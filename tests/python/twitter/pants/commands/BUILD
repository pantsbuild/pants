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
    pants('src/python/pants/commands:goal'),
  ]
)

python_tests(
  name = 'test_setup_py',
  sources = [ 'test_setup_py.py' ],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:setup_py'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:python'),
  ]
)
