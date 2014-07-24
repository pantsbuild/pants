# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'graph',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:build_root'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ],
)
