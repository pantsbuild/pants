# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

resource(name="lock", source="pyoxidizer.lock")

python_sources(overrides={"subsystem.py": {"dependencies": [":lock"]}})

python_tests(
    name="tests",
    overrides={"rules_integration_test.py": {"timeout": 480}},
)
