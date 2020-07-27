# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with Pants.
python_binary(
  dependencies=[
    'examples/src/python/example/hello/greet:greet',
    ':lib',
  ],
)

python_library(
    name='lib',
)
