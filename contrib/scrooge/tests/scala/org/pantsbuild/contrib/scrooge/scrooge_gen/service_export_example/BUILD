scala_library(
  dependencies=[
    ':dep_2'
  ],
  sources=["ToBeCompiled.scala"],
  strict_deps=True
)

scala_library(
  name="dep_2",
  dependencies=[
    ':dep'
  ],
  sources=["DependedUpon.scala"],
  strict_deps=True
)

scala_library(
  name="dep",
  sources=["Exported.scala"],
  strict_deps=True
)