# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'net',
  sources = rglobs('*.py'),
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.quantity'),
    pants('3rdparty/python:requests'),
  ],
)
