# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This java_library() target transitively depending on an rsc-compiled scala_library() target
# triggers some logic to traverse more deeply through dependencies to get the complete classpath.
java_library(
  name = 'java-in-different-package',
  sources = ['Java.java'],
  dependencies = [':scala-in-different-package'],
  strict_deps = True,
)

scala_library(
  name = 'scala-in-different-package',
  sources = ['ScalaInDifferentPackage.scala'],
  dependencies = [':scala'],
  exports = [':scala'],
  strict_deps = True,
)

scala_library(
  name = 'scala',
  sources = ['Scala.scala'],
  dependencies = [':scala-2'],
  exports = [':scala-2'],
  tags = {'use-compiler:rsc-and-zinc'},
)

scala_library(
  name = 'scala-2',
  sources = ['Scala2.scala'],
  tags = {'use-compiler:rsc-and-zinc'},
)
