# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Substitutions for classes with static methods, which aren't available in Scala.
java_library(
  name='statics',
  provides=artifact(
    org='org.pantsbuild',
    name='zinc-compiler-native-image-substitutions',
    repo=public,
    publication_metadata=pants_library('Native-image substitutions for Zinc.')
  ),
)

scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-compiler-native-image-substitutions-scala',
    repo=public,
    publication_metadata=pants_library('Native-image substitutions for Zinc.')
  ),
)
