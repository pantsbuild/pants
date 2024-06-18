# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lockfile", source="black.lock")
# Lockfile for the version of Black Pants used to provide (with the '23 stable style), to make
# upgrading easier
resource(name="lockfile-23.3", source="black-23.3.lock")

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfile"]}},
)

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "tags": ["platform_specific_behavior"],
            "timeout": 240,
        }
    },
)
