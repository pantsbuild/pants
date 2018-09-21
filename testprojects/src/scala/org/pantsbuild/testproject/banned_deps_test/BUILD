scala_library(
    name = "banpackages",
    sources = ["Main.scala"],
    dependency_constraints =
        DependencyConstraints(
            direct = [
                DependencyConstraint.JvmPackageConstraint("scopt"),
            ],
            transitive = [
                DependencyConstraint.JvmPackageConstraint("never.Triggered"),
            ],
        ),
    dependencies = [
        "3rdparty/jvm/com/github/scopt",
    ],
)

scala_library(
    name = "bantags",
    sources = ["Main.scala"],
    dependency_constraints =
        DependencyConstraints(
            direct = [
            ],
            transitive = [
                DependencyConstraint.Tag("deprecated"),
            ],
        ),
    dependencies = [
        ":nodeps",
    ],
)

scala_library(
    name = "nodeps",
    sources = ["Main.scala"],
    tags = ["deprecated"],
)
