# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    sources = ["test_testprojects_integration.py"],
    tags = {"integration"},
    timeout = 950,
    dependencies = [
        ":base",
        "src/python/pants/util:contextutil",
    ],
)

python_library(
    name = "base",
    sources = ["base_project_integration_test.py"],
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)
