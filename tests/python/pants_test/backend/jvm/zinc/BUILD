# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies = [
    ':testdata',
    'src/python/pants/backend/jvm/zinc',
    'src/python/pants/util:contextutil',
  ]
)

resources(
  name='testdata',
  sources=rglobs('testdata/*')
)
