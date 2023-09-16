# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="bin_name",
    sources=["bin_name_integration_test.py"],
    dependencies=["testprojects/src/python:hello_directory"],
    timeout=240,
)

python_tests(
    name="build_ignore_integration", sources=["build_ignore_integration_test.py"], timeout=240
)

python_tests(
    name="goal_rule_integration",
    sources=["goal_rule_integration_test.py"],
    dependencies=["testprojects/src/python:hello_directory"],
    timeout=330,
)

python_tests(
    name="graph_integration",
    sources=["graph_integration_test.py"],
    dependencies=[
        "testprojects/src/python:no_build_file_directory",
        "testprojects/src/python:sources_directory",
    ],
    timeout=180,
)

python_tests(
    name="list_integration",
    sources=["list_integration_test.py"],
    dependencies=["testprojects/src/python:hello_directory"],
    timeout=240,
)

python_tests(name="prelude_integration", sources=["prelude_integration_test.py"], timeout=180)

python_tests(
    name="remote_cache_integration",
    sources=["remote_cache_integration_test.py"],
    dependencies=["testprojects/src/jvm:lib_directory"],
    timeout=180,
)

python_tests(
    name="pep561_integration",
    sources=["pep561_integration_test.py"],
    timeout=300,
    runtime_package_dependencies=[
        "src/python/pants:pants-packaged",
        "src/python/pants/testutil:testutil_wheel",
    ],
)

python_tests(
    name="plugin_requirements_integration",
    sources=["plugin_requirements_integration_test.py"],
    timeout=240,
    dependencies=[
        "testprojects:pants_plugins_directory",
    ],
)
