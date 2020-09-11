# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    name="projects_test_base",
    sources=["projects_test_base.py"],
    dependencies=["src/python/pants/testutil:int-test",],
    tags={"partially_type_checked"},
)

python_tests(
    name="java_examples_integration",
    sources=["test_java_examples_integration.py"],
    dependencies=[
        ":projects_test_base",
        "examples/src/java/org/pantsbuild/example:all_directories",
        "examples/tests/java/org/pantsbuild/example:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="java_testprojects_integration",
    sources=["test_java_testprojects_integration.py"],
    dependencies=[
        ":projects_test_base",
        "testprojects/src/java/org/pantsbuild/testproject:all_directories",
        "testprojects/tests/java/org/pantsbuild:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="maven_layout_integration",
    sources=["test_maven_layout_integration.py"],
    dependencies=[":projects_test_base", "testprojects/maven_layout:all_directories",],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="protobuf_projects_integration",
    sources=["test_protobuf_projects_integration.py"],
    dependencies=[
        ":projects_test_base",
        "examples/src/protobuf/org/pantsbuild/example:all_directories",
        "testprojects/src/protobuf/org/pantsbuild/testproject:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=500,
)

python_tests(
    name="python_examples_integration",
    sources=["test_python_examples_integration.py"],
    dependencies=[
        ":projects_test_base",
        "examples/src/python/example:all_directories",
        "examples/tests/python/example_test:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
)

python_tests(
    name="python_testprojects_src_integration",
    sources=["test_python_testprojects_src_integration.py"],
    dependencies=[":projects_test_base", "testprojects/src/python:all_directories",],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="python_testprojects_tests_integration",
    sources=["test_python_testprojects_tests_integration.py"],
    dependencies=[":projects_test_base", "testprojects/tests/python:all_directories",],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="scala_examples_integration",
    sources=["test_scala_examples_integration.py"],
    dependencies=[
        ":projects_test_base",
        "examples/src/scala/org/pantsbuild/example:all_directories",
        "examples/tests/scala/org/pantsbuild/example:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=700,
)

python_tests(
    name="scala_testprojects_integration",
    sources=["test_scala_testprojects_integration.py"],
    dependencies=[
        ":projects_test_base",
        "testprojects/src/scala/org/pantsbuild/testproject:all_directories",
        "testprojects/tests/scala/org/pantsbuild/testproject:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)

python_tests(
    name="thrift_projects_integration",
    sources=["test_thrift_projects_integration.py"],
    dependencies=[
        ":projects_test_base",
        "examples/src/thrift/org/pantsbuild/example:all_directories",
        "testprojects/src/thrift/org/pantsbuild:all_directories",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=600,
)
