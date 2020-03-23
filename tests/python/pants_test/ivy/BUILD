# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='bootstrapper',
  sources=['test_bootstrapper.py'],
  dependencies=[
    'build-support/ivy:ivy',
    'src/python/pants/ivy',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='ivy_subsystem',
  sources=['test_ivy_subsystem.py'],
  dependencies=[
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)
