# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'net',
  sources = rglobs('*.py'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.quantity'),
    pants('3rdparty/python:requests'),
    pants('src/python/pants/util:dirutil'),
  ],
)
