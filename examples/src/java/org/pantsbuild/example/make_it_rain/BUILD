# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This target is useful to be able to compile the referenced thrift targets,
# or to publish them. Try running
#
#  `./pants publish src/java/org/pantsbuild/example/make_it_rain --publish-local=/tmp --no-publish-dryrun --doc-javadoc-skip`
#
# to test it out.

java_library(name='make_it_rain',
  sources=['MakeItRain.java',],
  dependencies=[
    'examples/src/thrift/org/pantsbuild/example/distance:distance-java',
    'examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-java',
  ],
  provides = artifact(org='org.pantsbuild.example',
                      name='make-it-rain',
                      repo=public),
)
