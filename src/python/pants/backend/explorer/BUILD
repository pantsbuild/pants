# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Avoid leakage of the explorer backend sources, in order to isolate the 3rdparty requirements
# needed for the explorer within the `pantsbuild.pants.explorer-server` distribution.
__defaults__(all=dict(visibility=[f"{build_file_dir()}::"]))

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
