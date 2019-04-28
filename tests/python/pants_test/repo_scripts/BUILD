# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='repo-script-test-base',
  dependencies=[
    'src/python/pants/util:process_handler',
    'src/python/pants/util:strutil',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/testutils:git_util',
  ],
)

python_tests(
  name='git-hooks',
  sources=['test_git_hooks.py'],
  dependencies=[
    ':repo-script-test-base',
    '3rdparty/python:future',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/testutils:git_util',
  ],
)

python_tests(
  name='pants-bootstrap',
  sources=['test_pants_bootstrap.py'],
  dependencies=[
    ':repo-script-test-base',
    '3rdparty/python:ansicolors',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
  ],
)
