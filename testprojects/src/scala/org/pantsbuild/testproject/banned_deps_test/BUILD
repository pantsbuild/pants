# Target that bans a package in a third party dependency
scala_library(
    name="ban_packages",
    sources=["Main.scala"],
    dependency_constraints=
        DependencyConstraints([
                JvmPackageConstraint("scopt"),
                JvmPackageConstraint("never.Triggered"),
            ],
        ),
    dependencies=[
        "3rdparty/jvm/com/github/scopt",
    ],
)

# Target that bans a tag in another target
scala_library(
    name="nodeps",
    sources=["Main.scala"],
    tags=["deprecated"],
)

scala_library(
    name="ban_tags",
    sources=["Main.scala"],
    dependency_constraints=
        DependencyConstraints([
                Tag("deprecated"),
            ]
        ),
    dependencies=[
        ":nodeps",
    ],
)

# Ban test dependencies
junit_tests(
    name="testlib",
    sources=["Spec.scala"]
)

scala_library(
    name="ban_testdeps",
    sources=["Main.scala"],
    dependencies=[":testlib"],
    dependency_constraints=DependencyConstraints(
        [TestDependencies()]
    )
)
