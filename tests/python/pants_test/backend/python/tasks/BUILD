# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    name="python_task_test_base",
    sources=["python_task_test_base.py"],
    dependencies=[
        "src/python/pants/backend/python:plugin",
        "src/python/pants/backend/python/targets",
        "src/python/pants/build_graph",
        "src/python/pants/subsystem",
        "src/python/pants/testutil/subsystem",
        "src/python/pants/testutil:task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="build_local_python_distributions",
    sources=["test_build_local_python_distributions.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/backend/python/targets",
        "src/python/pants/python",
        "tests/python/pants_test/backend/python/tasks/util",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="build_local_python_distributions_integration",
    sources=["test_build_local_python_distributions_integration.py"],
    dependencies=[
        "src/python/pants/util:collections",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "testprojects/src/python:python_distribution_directory",
        "testprojects/tests/python:example_test_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=750,
)

python_tests(
    name="gather_sources",
    sources=["test_gather_sources.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/backend/python:interpreter_cache",
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/python",
        "src/python/pants/source",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="interpreter_selection_integration",
    sources=["test_interpreter_selection_integration.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "src/python/pants/testutil:interpreter_selection_utils",
        "testprojects/src/python:interpreter_selection_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=400,
)

python_tests(
    name="pytest_run",
    sources=["test_pytest_run.py"],
    dependencies=[
        "3rdparty/python:coverage",
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:exceptions",
        "src/python/pants/build_graph",
        "src/python/pants/source",
        "src/python/pants/util:contextutil",
        "src/python/pants/util:dirutil",
        "src/python/pants/testutil:task_test_base",
        "src/python/pants/testutil/subsystem",
        ":python_task_test_base",
    ],
    tags={"partially_type_checked"},
    timeout=480,
)

python_tests(
    name="pytest_run_integration",
    sources=["test_pytest_run_integration.py"],
    dependencies=[
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "src/python/pants/testutil:interpreter_selection_utils",
        "src/python/pants/testutil:pexrc_util",
        "examples:3rdparty_directory",
        "testprojects/src/python:interpreter_selection_directory",
        "testprojects/tests/python/pants:conf_test_directory",
        "testprojects/tests/python/pants:constants_only_directory",
        "testprojects/tests/python/pants:timeout_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=850,
)

python_tests(
    name="pytest_run_timeout_integration",
    sources=["test_pytest_run_timeout_integration.py"],
    dependencies=[
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "src/python/pants/testutil:interpreter_selection_utils",
        "src/python/pants/testutil:pexrc_util",
        "examples:3rdparty_directory",
        "testprojects/src/python:interpreter_selection_directory",
        "testprojects/tests/python/pants:conf_test_directory",
        "testprojects/tests/python/pants:constants_only_directory",
        "testprojects/tests/python/pants:timeout_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=400,
)

python_tests(
    name="python_binary_create",
    sources=["test_python_binary_create.py"],
    dependencies=[
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:run_info",
        "src/python/pants/build_graph",
        ":python_task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="python_binary_integration",
    sources=["test_python_binary_integration.py"],
    dependencies=[
        "3rdparty/python:pex",
        "examples/src/python/example/tensorflow_custom_op:show-tf-version-files",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "testprojects/src/python:python_distribution_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=850,
)

python_tests(
    name="python_repl",
    sources=["test_python_repl.py"],
    dependencies=[
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:exceptions",
        "src/python/pants/build_graph",
        "src/python/pants/task",
        "src/python/pants/util:contextutil",
        ":python_task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="python_repl_integration",
    sources=["test_python_repl_integration.py"],
    dependencies=[
        "src/python/pants/testutil:int-test",
        "testprojects/src/python:interpreter_selection_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=500,
)

python_tests(
    name="python_run_integration",
    sources=["test_python_run_integration.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:int-test",
        "src/python/pants/testutil:interpreter_selection_utils",
        "src/python/pants/testutil:pexrc_util",
        "testprojects/src/python:interpreter_selection_directory",
        "testprojects/src/python:print_env_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=900,
)

python_tests(
    name="python_tool",
    sources=["test_python_tool.py"],
    dependencies=[
        "src/python/pants/backend/python/subsystems",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/task",
        "src/python/pants/util:contextutil",
        ":python_task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="resolve_requirements",
    sources=["test_resolve_requirements.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/backend/python:interpreter_cache",
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:build_environment",
        "src/python/pants/python",
        "src/python/pants/task",
        "src/python/pants/util:contextutil",
        "src/python/pants/testutil:task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="select_interpreter",
    sources=["test_select_interpreter.py"],
    dependencies=[
        "3rdparty/python:pex",
        "src/python/pants/backend/python:interpreter_cache",
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:exceptions",
        "src/python/pants/python",
        "src/python/pants/util:dirutil",
        "src/python/pants/testutil:task_test_base",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="setup_py",
    sources=["test_setup_py.py"],
    dependencies=[
        "3rdparty/python/twitter/commons:twitter.common.dirutil",
        "3rdparty/python:pex",
        ":python_task_test_base",
        "src/python/pants/backend/python/subsystems",
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/base:exceptions",
        "src/python/pants/build_graph",
        "src/python/pants/fs",
        "src/python/pants/util:contextutil",
        "src/python/pants/util:dirutil",
        "src/python/pants/util:ordered_set",
        "src/python/pants/testutil/subsystem",
        "src/python/pants/testutil:interpreter_selection_utils",
    ],
    tags={"partially_type_checked"},
)

python_tests(
    name="setup_py_integration",
    sources=["test_setup_py_integration.py"],
    dependencies=[
        "tests/python/pants_test/backend/python:pants_requirement_integration_test_base",
        "examples:3rdparty_directory",
        "examples/src/thrift/org/pantsbuild/example:distance_directory",
        "examples/src/thrift/org/pantsbuild/example:precipitation_directory",
        "testprojects:pants_plugins_directory",
    ],
    tags={"integration", "partially_type_checked"},
    timeout=240,
)


python_tests(
    name="unpack_wheels",
    sources=["test_unpack_wheels.py"],
    dependencies=[
        "src/python/pants/backend/python/targets",
        "src/python/pants/backend/python/tasks",
        "src/python/pants/python",
        "src/python/pants/task",
        "src/python/pants/util:collections",
        "src/python/pants/testutil:task_test_base",
    ],
    tags={"partially_type_checked"},
)
