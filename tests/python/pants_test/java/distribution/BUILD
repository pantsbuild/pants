# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources = ['test_distribution.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'src/python/pants/java/distribution',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
  timeout = 15,
)

python_tests(
  name = 'distribution_integration',
  sources = ['test_distribution_integration.py'],
  dependencies = [
    'src/python/pants/java/distribution',
    'src/python/pants/util:osutil',
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil/subsystem',
    'testprojects/src/java/org/pantsbuild/testproject:printversion_directory'
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 700,
)
