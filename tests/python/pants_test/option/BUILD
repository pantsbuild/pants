# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='testing',
  sources=globs('*.py', exclude=[globs('*_integration.py')]),
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='options_integration',
  sources=[
    'test_options_integration.py',
  ],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
