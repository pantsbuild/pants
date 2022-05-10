# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="mypy.lock")

python_tests(name="subsystem_test", sources=["subsystem_test.py"], timeout=180)
python_tests(
    name="rules_integration_test",
    sources=["rules_integration_test.py"],
    timeout=480,
    # We want to make sure the default lockfile works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
python_tests(
    name="mypyc_integration_test",
    sources=["mypyc_integration_test.py"],
    dependencies=["testprojects/src/python:mypyc_fib_directory"],
    timeout=120,
    # We want to make sure we can build with mypyc on both macOS and Linux.
    tags=["platform_specific_behavior"],
)
