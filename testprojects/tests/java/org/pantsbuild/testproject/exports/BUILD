java_library(
    name = "A",
    sources = ["A.java"],
)

java_library(
    name = "B",
    sources = ["B.java"],
    strict_deps = True,
    dependencies = [":A"],
    exports = [":A"],
)

java_library(
    name = "C",
    sources = ["C.java"],
    strict_deps = True,
    dependencies = [":B"],
    exports = [":B"],
)

java_library(
    name = "D",
    sources = ["D.java"],
    strict_deps = True,
    dependencies = [":C"],
)
