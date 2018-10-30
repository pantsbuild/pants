# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=globs('test_*.py', exclude=[globs('*_integration.py')]),
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:mock',
    'src/python/pants/binaries',
    'src/python/pants/net',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='integration',
  sources=globs('test_*_integration.py'),
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/util:process_handler',
  ]
)
