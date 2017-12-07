scala_library(
    name = "A",
    sources = ["A.scala"],
)

scala_library(
    name = "B",
    sources = ["B.scala"],
    strict_deps = True,
    dependencies = [":A"],
    exports = [":A"],
)

scala_library(
    name = "C",
    sources = ["C.scala"],
    strict_deps = True,
    dependencies = [":B"],
    exports = [":B"],
)

scala_library(
    name = "D",
    sources = ["D.scala"],
    strict_deps = True,
    dependencies = [":C"],
)

target(
    name = "TB",
    dependencies = [":B"],
)

scala_library(
    name = "TC",
    sources = ["C.scala"],
    strict_deps = True,
    dependencies = [":TB"],
    exports = [":TB"],
)

scala_library(
    name = "TD",
    sources = ["D.scala"],
    strict_deps = True,
    dependencies = [":TC"],
)
