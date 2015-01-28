# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'util',
  dependencies = [
    ':contextutil',
    ':dirutil',
    ':strutil',
    ':fileutil',
  ]
)

python_tests(
  name = 'contextutil',
  sources = ['test_contextutil.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'dirutil',
  sources = ['test_dirutil.py'],
  dependencies = [
    '3rdparty/python:mox',
    '3rdparty/python:pytest',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'strutil',
  sources = ['test_strutil.py'],
  dependencies = [
    'src/python/pants/util:strutil',
  ]
)

python_tests(
  name = 'keywords',
  sources = ['test_keywords.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:keywords',
  ]
)

python_tests(
  name = 'fileutil',
  sources = ['test_fileutil.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:fileutil',
  ]
)
