# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# trivial example of thrift that includes other thrift

java_thrift_library(name='precipitation-java',
  sources=['precipitation.thrift'],
  dependencies=[
    'examples/src/thrift/org/pantsbuild/example/distance:distance-java',
  ],
  provides = artifact(org='org.pantsbuild.example',
                      name='precipitation-thrift-java',
                      repo=public),
)

python_thrift_library(name='precipitation-python',
  sources=['precipitation.thrift'],
  dependencies=[
    'examples/src/thrift/org/pantsbuild/example/distance:distance-python',
  ],
)
