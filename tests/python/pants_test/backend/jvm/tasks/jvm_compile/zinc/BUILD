# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    name = "zinc_compile_integration_base",
    sources = ["zinc_compile_integration_base.py"],
    dependencies = [
        "src/python/pants/util:contextutil",
    ],
)

python_tests(
    name = "zinc_compile_integration_with_zjars",
    sources = ["test_zinc_compile_integration_with_zjars.py"],
    tags = {"integration"},
    timeout = 240,
    dependencies = [
        ":zinc_compile_integration_base",
        "tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test",
    ],
)

python_tests(
    name = "zinc_compile_integration",
    sources = ["test_zinc_compile_integration.py"],
    tags = {"integration"},
    timeout = 360,
    dependencies = [
        ":zinc_compile_integration_base",
        "tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test",
    ],
)
