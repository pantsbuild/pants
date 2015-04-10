# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'jar',
  dependencies = [
    ':manifest',
    ':shader'
  ]
)

python_tests(
  name = 'manifest',
  sources = ['test_manifest.py'],
  dependencies = [
    'src/python/pants/java/jar:manifest',
  ]
)

python_tests(
  name = 'shader',
  sources = ['test_shader.py'],
  dependencies = [
    'src/python/pants/java/jar:shader',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)
