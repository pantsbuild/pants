java_thrift_library(
    sources = ["struct.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    language = "android",
    dependencies = [
        "3rdparty:thrift-0.6.1",
        "contrib/scrooge/examples/src/thrift/org/pantsbuild/contrib/scrooge/dummy_generator",
    ],
)
