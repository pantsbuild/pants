# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='testing',
  sources=globs('*.py', exclude=[globs('*_integration.py')]),
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:deprecated',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
)

python_tests(
  name='options_integration',
  sources=globs('*_integration.py'),
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:plugins_directory',
  ],
  tags = {'integration'},
  timeout=90,
)
