# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# trivial example of "generally-useful" thrift to include in other thrift
# (to see how this is included, cd ../precipitation)

java_thrift_library(name='distance-java',
  sources=['distance.thrift'],
  provides = artifact(org='org.pantsbuild.example',
                      name='distance-thrift-java',
                      repo=public),
)

python_thrift_library(name='distance-python',
  sources=['distance.thrift'],
)
