# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This doesn't test much. It shows Pants-ly using Thrift from Python, though.

python_tests(name='usethrift',
  sources=['use_thrift_test.py',],
  dependencies=[
    'examples/src/thrift/org/pantsbuild/example/distance:distance-python',
    'examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-python',
  ],
)


