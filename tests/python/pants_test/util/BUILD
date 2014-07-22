# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name = 'util',
  dependencies = [
    pants(':contextutil'),
    pants(':dirutil'),
  ]
)

python_tests(
  name = 'contextutil',
  sources = ['test_contextutil.py'],
  dependencies = [
    pants('src/python/pants/util:contextutil'),
  ]
)

python_tests(
  name = 'dirutil',
  sources = ['test_dirutil.py'],
  dependencies = [
    pants('3rdparty/python:mox'),
    pants('3rdparty/python:pytest'),
    pants('src/python/pants/util:dirutil'),
  ]
)
