scala_library(
    name = "A",
    sources = ["A.scala"],
)

scala_library(
    name = "B",
    sources = ["B.scala"],
    strict_deps = True,
    dependencies = [":A"],
)

scala_library(
    name = "C",
    sources = ["C.scala"],
    strict_deps = True,
    dependencies = [":B"],
)
