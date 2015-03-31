# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'java',
  dependencies = [
    ':executor',
    'tests/python/pants_test/java/distribution',
    'tests/python/pants_test/java/jar',
  ]
)

python_tests(
  name = 'executor',
  sources = ['test_executor.py'],
  dependencies = [
    'src/python/pants/java/distribution:distribution',
    'src/python/pants/java:executor',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)
