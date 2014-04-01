# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'http',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python:mox'),
    pants('3rdparty/python:requests'),
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.quantity'),
    pants('src/python/pants/net'),
  ]
)
