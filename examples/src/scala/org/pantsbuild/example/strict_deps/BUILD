# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  name = "a",
  sources = ["A.scala"],
)

scala_library(
  name = "b",
  sources = ["B.scala"],
)

scala_library(
  name = "c",
  sources = ["C.scala"],
  dependencies = [":a"],
)

scala_library(
  name = "d",
  sources = ["D.scala"],
  dependencies = [":b", ":c"],
  strict_deps = True,
)

scala_library(
  name = "e",
  sources = ["E.scala"],
  dependencies = [":b", ":c"],
  strict_deps = False,
)
