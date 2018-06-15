java_thrift_library(
    name = "A",
    sources = [
        "A.thrift",
    ],
    compiler = "scrooge",
    language = "scala",
)

java_thrift_library(
    name = "B-with-exports",
    sources = [
        "B.thrift",
    ],
    compiler = "scrooge",
    language = "scala",
    dependencies = [
        ":A",
    ],
    exports = [
        ":A",
    ],
)

java_thrift_library(
    name = "B-without-exports",
    sources = [
        "B.thrift",
    ],
    compiler = "scrooge",
    language = "scala",
    dependencies = [
        ":A",
    ],
)

java_thrift_library(
    name = "C-with-exports",
    sources = [
        "C.thrift",
    ],
    compiler = "scrooge",
    language = "scala",
    strict_deps = True,
    dependencies = [
        ":B-with-exports",
    ],
)

java_thrift_library(
    name = "C-without-exports",
    sources = [
        "C.thrift",
    ],
    compiler = "scrooge",
    language = "scala",
    strict_deps = True,
    dependencies = [
        ":B-without-exports",
    ],
)
