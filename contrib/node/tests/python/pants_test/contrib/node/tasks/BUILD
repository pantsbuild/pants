# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
    name = "node_build",
    sources = ["test_node_build.py"],
    timeout = 30,
    dependencies = [
        "contrib/node/src/python/pants/contrib/node/targets:node_module",
        "contrib/node/src/python/pants/contrib/node/tasks:node_build",
        "src/python/pants/build_graph",
        "src/python/pants/util:contextutil",
        "src/python/pants/util:dirutil",
        "tests/python/pants_test:task_test_base",
    ],
)

python_tests(
    name = "node_bundle",
    sources = ["test_node_bundle.py"],
    timeout = 30,
    dependencies = [
        "contrib/node/src/python/pants/contrib/node/targets:node_bundle",
        "contrib/node/src/python/pants/contrib/node/targets:node_module",
        "contrib/node/src/python/pants/contrib/node/tasks:node_bundle",
        "src/python/pants/build_graph",
        "tests/python/pants_test:task_test_base",
    ],
)

python_tests(
    name = "node_bundle_integration",
    sources = ["test_node_bundle_integration.py"],
    tags = {"integration"},
    timeout = 300,
    dependencies = [
        "src/python/pants/fs",
        "src/python/pants/util:contextutil",
        "tests/python/pants_test:int-test",
    ],
)

python_tests(
    name = "node_repl_integration",
    sources = ["test_node_repl_integration.py"],
    tags = {"integration"},
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)

python_tests(
    name = "node_resolve_integration",
    sources = ["test_node_resolve_integration.py"],
    tags = {"integration"},
    timeout = 180,
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)

python_tests(
    name = "node_run_integration",
    sources = ["test_node_run_integration.py"],
    tags = {"integration"},
    timeout = 180,
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)

python_tests(
    name = "node_test_integration",
    sources = ["test_node_test_integration.py"],
    tags = {"integration"},
    timeout = 240,
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)

python_tests(
    name = "node_task",
    sources = ["test_node_task.py"],
    dependencies = [
        "contrib/node/src/python/pants/contrib/node/targets:node_module",
        "contrib/node/src/python/pants/contrib/node/targets:node_remote_module",
        "contrib/node/src/python/pants/contrib/node/targets:node_test",
        "contrib/node/src/python/pants/contrib/node/tasks:node_paths",
        "contrib/node/src/python/pants/contrib/node/tasks:node_task",
        "src/python/pants/build_graph",
        "src/python/pants/util:contextutil",
        "tests/python/pants_test:task_test_base",
    ],
)

python_tests(
    name = "node_resolve",
    sources = ["test_node_resolve.py"],
    dependencies = [
        "3rdparty/python:mock",
        "contrib/node/src/python/pants/contrib/node/subsystems/resolvers:node_preinstalled_module_resolver",
        "contrib/node/src/python/pants/contrib/node/subsystems/resolvers:npm_resolver",
        "contrib/node/src/python/pants/contrib/node/targets:node_module",
        "contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module",
        "contrib/node/src/python/pants/contrib/node/targets:node_remote_module",
        "contrib/node/src/python/pants/contrib/node/targets:node_test",
        "contrib/node/src/python/pants/contrib/node/tasks:node_paths",
        "contrib/node/src/python/pants/contrib/node/tasks:node_resolve",
        "src/python/pants/build_graph",
        "tests/python/pants_test:task_test_base",
    ],
)

python_tests(
    name = "node_lint_integration",
    sources = ["test_node_lint_integration.py"],
    tags = {"integration"},
    timeout = 180,
    dependencies = [
        "tests/python/pants_test:int-test",
    ],
)
