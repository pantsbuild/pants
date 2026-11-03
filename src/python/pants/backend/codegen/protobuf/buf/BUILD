# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        "generate_integration_test.py": {
            # On a cold cache this downloads buf and protoc, builds a PEX plugin, and calls the
            # BSR for a remote plugin.
            "timeout": 330,
            # Runs the platform-specific buf and protoc binaries.
            "tags": ["platform_specific_behavior"],
        }
    },
)
