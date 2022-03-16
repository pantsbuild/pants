# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="pylint.lock")

python_tests(name="subsystem_test", sources=["subsystem_test.py"], timeout=420)
python_tests(
    name="rules_integration_test",
    sources=["rules_integration_test.py"],
    timeout=330,
    # We want to make sure the default lockfile works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
