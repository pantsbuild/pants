# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="black.lock")

python_tests(name="subsystem_test", sources=["subsystem_test.py"])
python_tests(
    name="rules_integration_test",
    sources=["rules_integration_test.py"],
    timeout=240,
    # We want to make sure the default lockfile works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
