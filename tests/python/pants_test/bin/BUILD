# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'exiter',
  sources = ['test_exiter.py'],
  dependencies = [
    'src/python/pants/bin',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/option:testing',
  ],
)

python_tests(
  name='exe_integration',
  sources=['test_exe_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='repro',
  sources=['test_repro.py'],
  dependencies=[
    ':repro_mixin',
    'src/python/pants/bin',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name='repro_ignore',
  sources=['test_repro_ignore.py'],
  dependencies=[
    ':repro_mixin',
    'src/python/pants/base:build_root',
    'src/python/pants/bin',
    'src/python/pants/fs',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)

python_library(
  name='repro_mixin',
  sources=['repro_mixin.py'],
  dependencies=[
    'src/python/pants/util:dirutil',
  ]
)
