# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='git-hook-test-mixin',
  sources=[
    'git_hook_test_mixin.py',
  ],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/testutils:git_util',
  ],
)

python_tests(
  name='git-hooks',
  sources=[
    'test_git_hooks.py',
  ],
  dependencies=[
    ':git-hook-test-mixin',
  ],
)

python_tests(
  name='git-hooks-integration',
  sources=[
    'test_git_hooks_integration.py',
  ],
  dependencies=[
    ':git-hook-test-mixin',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)
