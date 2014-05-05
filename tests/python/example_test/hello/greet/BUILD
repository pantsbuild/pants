# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The greet library doesn't do much, but we should still test it

python_tests(name='greet',
  dependencies=[
    pants('src/python/example/hello/greet:greet'),
  ],
  sources=globs('*.py'),
)