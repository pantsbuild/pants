# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    # On a cold cache this downloads buf, protoc and Node.js, and installs a Node package.
    timeout=330,
    # Runs the platform-specific buf, protoc and Node.js binaries.
    tags=["platform_specific_behavior"],
)
