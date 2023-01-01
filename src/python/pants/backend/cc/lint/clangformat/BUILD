# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="clangformat.lock")

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": {"timeout": 240},
    },
)
