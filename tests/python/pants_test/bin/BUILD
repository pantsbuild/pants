# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name='integration',
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/bin',
    'src/python/pants/option',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='daemon_pants_runner',
  dependencies=[
    'src/python/pants/base:exiter',
    'src/python/pants/bin',
    'tests/python/pants_test:test_infra',
  ]
)
