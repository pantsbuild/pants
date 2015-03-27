# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'util',
  dependencies = [
    ':contextutil',
    ':dirutil',
    ':fileutil',
    ':meta',
    ':strutil',
    ':xml_parser',
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
  name = 'meta',
  sources = ['test_meta.py'],
  dependencies = [
    'src/python/pants/util:meta',
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

python_tests(
  name = 'strutil',
  sources = ['test_strutil.py'],
  dependencies = [
    'src/python/pants/util:strutil',
  ]
)

python_tests(
  name = 'xml_parser',
  sources = ['test_xml_parser.py'],
  dependencies = [
    'src/python/pants/util:xml_parser',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'test_binaryutil',
  sources = ['test_binaryutil.py',],
  dependencies = [
    'src/python/pants/util:binaryutil',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'test_thriftutil',
  sources = ['test_thriftutil.py'],
  dependencies = [
    ':base_test',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:thriftutil',
  ]
)
