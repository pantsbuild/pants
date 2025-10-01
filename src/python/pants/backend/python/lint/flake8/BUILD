# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resources(name="lockfile", sources=["flake8.lock*"])

resources(name="test_lockfile", sources=["flake8_plugin_test.lock*"])

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfile"]}},
)

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {
            "timeout": 240,
            "tags": ["platform_specific_behavior"],
            "dependencies": [":test_lockfile"],
        }
    },
)
