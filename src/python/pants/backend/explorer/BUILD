# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_distribution(
    name="dist",
    provides=python_artifact(
        name="pantsbuild.pants.explorer-server",
        description="Backend API server implementation for the Pants Explorer UI.",
        classifiers=["Topic :: Software Development"],
    ),
    entry_points={
        "pantsbuild.plugin": {
            "rules": "pants.backend.explorer.register:rules",
        }
    },
)

python_tests(
    name="tests",
    dependencies=[":explorer"],
)


__dependents_rules__(
    # Block any outside sources from pulling in code from this backend, as it is self contained and
    # have 3rd party dependencies that we don't want to leak to the core Pants distribution.
    (
        "*",
        build_file_dir() / "**",
        "!*",
    ),
)
