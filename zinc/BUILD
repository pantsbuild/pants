# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  name='compiler',
  main='org.pantsbuild.zinc.compiler.Main',
  dependencies=[
    'src/scala/org/pantsbuild/zinc/compiler',
    # NB: There is a warning generated about some "unsafe" methods used in protobuf (which is
    # a transitive dependency) when building with native-image unless this protobuf dependency is
    # added.
    '3rdparty/jvm/com/google/protobuf:protobuf-java',
    # We don't want to inject the compiler bridge into the jar we distribute, but we do want it in
    # this jvm_binary() in order to create native-image versions of our zinc wrapper.
    '3rdparty/jvm/org/scala-sbt:sbt-compiler-bridge',
  ],
  description='zinc compiler -- the scala compiler in nailgun',
)
