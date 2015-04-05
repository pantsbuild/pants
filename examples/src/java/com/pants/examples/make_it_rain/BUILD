# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This target is useful to be able to compile the referenced thrift targets,
# or to publish them. Try running
#
#  `./pants publish src/java/com/pants/examples/make_it_rain --publish-local=/tmp --no-publish-dryrun --doc-javadoc-skip`
#
# to test it out.

java_library(name='make_it_rain',
  sources=['MakeItRain.java',],
  dependencies=[
    'examples/src/thrift/com/pants/examples/distance:distance-java',
    'examples/src/thrift/com/pants/examples/precipitation:precipitation-java',
  ],
  provides = artifact(org='com.pants.examples',
                      name='make-it-rain',
                      repo=public),
)
