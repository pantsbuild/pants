# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'ivy',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.log'),
    pants('src/python/pants/BUILD.commons:twitter.common.quantity'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/net'),
  ]
)
