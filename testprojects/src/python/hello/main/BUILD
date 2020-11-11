# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with Pants.
pex_binary(
    sources=['main.py'],
  dependencies=[
    'testprojects/src/python/hello/greet:greet',
    ':lib',
  ],
)

python_library(
    name='lib',
)
