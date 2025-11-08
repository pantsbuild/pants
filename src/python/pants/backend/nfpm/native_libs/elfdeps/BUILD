# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="lockfile", sources=["elfdeps.lock*"])

python_sources(
    overrides={
        "subsystem.py": dict(
            dependencies=[
                ":lockfile",
                "./analyze.py",
            ]
        ),
    },
)

python_tests(
    name="tests",
)
