# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    name = "build_invalidator",
    sources = ["test_build_invalidator.py"],
    dependencies = [
        "src/python/pants/invalidation",
        "src/python/pants/util:contextutil",
        "src/python/pants/util:dirutil",
        "tests/python/pants_test/subsystem:subsystem_utils",
    ],
)

python_tests(
    name = "cache_manager",
    sources = ["test_cache_manager.py"],
    dependencies = [
        "src/python/pants/invalidation",
        "src/python/pants/util:dirutil",
        "tests/python/pants_test:task_test_base",
        "tests/python/pants_test/testutils:mock_logger",
    ],
)

python_tests(
    name = "strict_deps_invalidation_integration",
    sources = ["test_strict_deps_invalidation_integration.py"],
    tags = {"integration"},
    timeout = 120,
    dependencies = [
        "src/python/pants/base:build_environment",
        "tests/python/pants_test:int-test",
    ],
)
