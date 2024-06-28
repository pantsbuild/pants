# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    dependencies=["src/python/pants/engine/internals:fs_test_data"],
    sources=["*_test.py", "!streaming_workunit_handler_integration_test.py"],
    timeout=90,
    overrides={
        "goal_test.py": {"dependencies": ["//BUILD_ROOT:files"]},
    },
)

python_tests(
    name="streaming_workunit_handler_integration_test",
    sources=["streaming_workunit_handler_integration_test.py"],
    dependencies=[
        # Loaded reflectively as a backend in `streaming_workunit_handler_integration_test.py`.
        "testprojects/pants-plugins/src/python/workunit_logger"
    ],
    timeout=240,
)
