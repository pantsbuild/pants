benchmark(
    sources = ["CaliperBench.java"],
    dependencies = [":caliper"],
)

jar_library(
    name = "caliper",
    jars = [
        jar(
            name = "caliper",
            org = "com.google.caliper",
            rev = "0.5-rc1",
            excludes = [
                exclude(
                    name = "guava",
                    org = "com.google.guava",
                ),
            ],
        ),
    ],
)

java_library(
    name = "jmh",
    sources = ["JmhBench.java"],
    # Turn off zinc provided file manager, incompatible with jmh.
    # See https://github.com/sbt/zinc/issues/185
    zinc_file_manager = False,
    dependencies = [
        "3rdparty/jvm/org/openjdk/jmh",
    ],
)
