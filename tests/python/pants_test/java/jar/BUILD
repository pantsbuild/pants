# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'jar',
  dependencies = [
    ':manifest',
  ]
)

python_tests(
  name = 'manifest',
  sources = ['test_manifest.py'],
  dependencies = [
    'src/python/pants/java/jar:manifest',
  ]
)
