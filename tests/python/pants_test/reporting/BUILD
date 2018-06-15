# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    sources = ["test_linkify.py"],
    timeout = 10,
    dependencies = [
        "src/python/pants/reporting",
    ],
)

python_tests(
    name = "reporting_integration",
    sources = ["test_reporting_integration.py"],
    tags = {"integration"},
    timeout = 240,
    dependencies = [
        "3rdparty/python:parameterized",
        "src/python/pants/util:contextutil",
        "tests/python/pants_test:int-test",
    ],
)
