# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    name = "javac_compile_integration",
    sources = ["test_javac_compile_integration.py"],
    tags = {"integration"},
    timeout = 240,
    dependencies = [
        "src/python/pants/util:contextutil",
        "tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test",
    ],
)
