# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='node_distribution',
  sources=['test_node_distribution.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/subsystems',
    'src/python/pants/testutil/base:context_utils',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='package_managers',
  sources=['test_package_managers.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/subsystems',
  ],
  tags = {"partially_type_checked"},
)
