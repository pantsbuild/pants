# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(
    name="lockfile",
    source="elfdeps.lock",
)

python_sources(
    overrides={
        "subsystem.py": dict(
            dependencies=[
                ":lockfile",
                "./analyze_wheels.py",
            ]
        ),
    },
)

python_tests(
    name="tests",
)
