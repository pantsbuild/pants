# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
   name = 'contextutil',
   sources = ['contextutil.py'],
   dependencies = [
     '3rdparty/python:six',
     ':dirutil',
   ],
)

python_library(
  name = 'dirutil',
  sources = ['dirutil.py'],
  dependencies = [
    ':strutil',
  ],
)

python_library(
  name = 'fileutil',
  sources = ['fileutil.py'],
  dependencies = [
    ':contextutil',
  ],
)

python_library(
  name = 'meta',
  sources = ['meta.py'],
)

python_library(
  name = 'strutil',
  sources = ['strutil.py'],
  dependencies = [
    '3rdparty/python:six',
  ],
)

python_library(
  name = 'xml_parser',
  sources = ['xml_parser.py'],
)

python_library(
  name='binaryutil',
  sources=['binaryutil.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/base:config',
    'src/python/pants/base:exceptions',
    ':contextutil',
    ':dirutil',
  ],
)

python_library(
  name='thriftutil',
  sources=['thriftutil.py'],
  dependencies=[
    ':binaryutil',
  ],
)
