# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={"native_engine.pyi": {"dependencies": [":native_engine"]}},
)

python_tests(
    name="tests",
    timeout=90,
    overrides={
        "engine_test.py": {"dependencies": ["//BUILD_ROOT:files"]},
        "graph_integration_test.py": {
            "dependencies": [
                "testprojects/src/python:no_build_file_directory",
                "testprojects/src/python:sources_directory",
            ],
            "timeout": 180,
        },
        "platform_rules_test.py": {"tags": ["platform_specific_behavior"], "timeout": 120},
        "remote_cache_integration_test.py": {
            "dependencies": ["testprojects/src/jvm:lib_directory"],
        },
        "scheduler_integration_test.py": {
            "dependencies": [
                "testprojects/src/python:hello_directory",
            ],
            "timeout": 180,
        },
    },
)

resources(
    name="native_engine",
    sources=["native_engine.so", "native_engine.so.metadata"],
)

resources(name="fs_test_data", sources=["fs_test_data/fs_test.tar", "fs_test_data/tls/rsa/*"])
