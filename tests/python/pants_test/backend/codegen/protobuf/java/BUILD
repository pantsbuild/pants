# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    sources = globs(
        "*.py",
        exclude = [globs("*_integration.py")],
    ),
    dependencies = [
        "src/python/pants/backend/codegen/protobuf/java",
        "src/python/pants/backend/jvm:plugin",
        "src/python/pants/backend/jvm/targets:jvm",
        "src/python/pants/backend/jvm/targets:scala",
        "src/python/pants/build_graph",
        "src/python/pants/java/jar",
        "src/python/pants/util:contextutil",
        "tests/python/pants_test:base_test",
        "tests/python/pants_test/tasks:task_test_base",
    ],
)

python_tests(
    name = "integration",
    sources = globs("*_integration.py"),
    tags = {"integration"},
    dependencies = [
        "src/python/pants/util:process_handler",
        "tests/python/pants_test:int-test",
    ],
)
