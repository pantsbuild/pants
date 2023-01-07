# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lockfile", source="ruff.lock")

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfile"]}},
)

python_tests(
    name="tests",
    overrides={
        "subsystem_test.py": {"timeout": 440},
        "rules_integration_test.py": {
            "timeout": 330,
            "tags": ["platform_specific_behavior"],
        },
    },
)
