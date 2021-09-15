# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(dependencies=[":lockfile"])
resources(name="lockfile", sources=["lambdex_lockfile.txt"])

python_tests(name='target_types_test', sources=["target_types_test.py"])
python_tests(
    name="rules_test",
    sources=["rules_test.py"],
    timeout=300,
    # We want to make sure the default lockfile works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
