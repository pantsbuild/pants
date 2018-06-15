target(
    dependencies = [
        ":one",
        ":three",
        ":two",
    ],
)

java_library(
    name = "base",
    dependencies = ["3rdparty:junit"],
)

junit_tests(
    name = "one",
    sources = ["OneTest.java"],
    strict_deps = False,
    dependencies = [":base"],
)

junit_tests(
    name = "two",
    sources = ["TwoTest.java"],
    strict_deps = False,
    dependencies = [":base"],
)

junit_tests(
    name = "three",
    sources = ["subtest/ThreeTest.java"],
    strict_deps = False,
    dependencies = [":base"],
)
