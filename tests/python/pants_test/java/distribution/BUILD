# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'distribution',
  sources = ['test_distribution.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'src/python/pants/java/distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ]
)

python_tests(
  name = 'distribution_integration',
  sources = ['test_distribution_integration.py'],
  dependencies = [
    'src/python/pants/java/distribution',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/subsystem:subsystem_utils',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
  tags = {'integration'},
)

