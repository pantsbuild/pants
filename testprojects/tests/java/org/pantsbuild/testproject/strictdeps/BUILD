java_library(
    name = "A1",
    sources = ["A.java"],
    strict_deps = True,
    dependencies = [":B"],
)

java_library(
    name = "A2",
    sources = ["A.java"],
    strict_deps = False,
    dependencies = [":B"],
)

java_library(
    name = "A3",
    sources = ["A.java"],
    dependencies = [":B"],
)

java_library(
    name = "A4",
    sources = ["A.java"],
    dependencies = [":B1"],
)

java_library(
    name = "B",
    sources = ["B.java"],
    dependencies = [":C"],
)

java_library(
    name = "B1",
    sources = ["B.java"],
    strict_deps = True,
    dependencies = [":C"],
)

java_library(
    name = "C",
    sources = ["C.java"],
    dependencies = [":D"],
)

java_library(
    name = "C1",
    sources = ["C.java"],
    strict_deps = True,
    dependencies = [":E"],
)

java_library(
    name = "D",
    sources = ["D.java"],
)

target(
    name = "E",
    dependencies = [":D"],
)
