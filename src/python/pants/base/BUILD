# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    sources=["*_test.py", "!exception_sink_test.py", "!*_integration_test.py"],
    overrides={
        "build_root_test.py": dict(
            dependencies=["//BUILD_ROOT:files"],
        )
    },
)

python_tests(
    name="exception_sink_test",
    sources=["exception_sink_test.py"],
    tags=["platform_specific_behavior"],
    timeout=180,
)

python_tests(
    name="exception_sink_integration_test",
    sources=["exception_sink_integration_test.py"],
    dependencies=[
        "testprojects/src/python:coordinated_runs_directory",
        "testprojects/src/python:hello_directory",
        "testprojects:pants_plugins_directory",
    ],
    tags=["platform_specific_behavior"],
    timeout=400,
)

python_tests(name="exiter_integration_test", sources=["exiter_integration_test.py"], timeout=180)

python_tests(name="specs_integration_test", sources=["specs_integration_test.py"], timeout=240)
