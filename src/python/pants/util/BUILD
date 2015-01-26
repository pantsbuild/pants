# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
   name = 'contextutil',
   sources = ['contextutil.py'],
   dependencies = [
     '3rdparty/python/twitter/commons:twitter.common.lang',
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
  name = 'strutil',
  sources = ['strutil.py'],
  dependencies = [
    '3rdparty/python:six',
  ],
)

python_library(
  name = 'keywords',
  sources = ['keywords.py'],
  dependencies = [
    ':strutil',
  ],
)
