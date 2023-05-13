# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="test",
    overrides={
        "rules_integration_test.py": dict(dependencies=[":lockfiles"], timeout=120),
    },
)

# The package.json file is inlined in ./rules_integration_tests.py
resources(name="lockfiles", sources=["package-lock.json", "pnpm-lock.yaml", "yarn.lock"])
