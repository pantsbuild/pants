# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This BUILD file defines common external library dependencies that are only needed for test projects.
# See also 3rdparty/BUILD for dependencies needed to run Pants and examples/3rdparty/BUILD for
# libraries needed by example projects.

jar_library(name='protobuf-test-import',
            jars = [
              jar(org='com.squareup.testing.protolib', name='protolib-test', rev='1.0.1'),
              ],
            )

jar_library(name='cucumber-java',
            jars=[
              jar(org='info.cukes', name='cucumber-java', rev='1.1.7'),
            ],
)

jar_library(name='shapeless',
            jars=[
              jar(org='com.chuusai', name='shapeless_2.9.2', rev='1.2.4'),
            ],
)


