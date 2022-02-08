# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":plugins"])

# NOTE: When adding a new backend, add it to `generate_docs.py` too! (If stable enough for docs)
target(
    name="plugins",
    dependencies=[
        "src/python/pants/backend/awslambda/python",
        "src/python/pants/backend/codegen/protobuf/python",
        "src/python/pants/backend/codegen/thrift/apache/python",
        "src/python/pants/backend/docker",
        "src/python/pants/backend/docker/lint/hadolint",
        "src/python/pants/backend/experimental/debian",
        "src/python/pants/backend/experimental/explorer",
        # Do NOT include the `pants.backend.experimental.explorer.server` module, as that pulls in a
        # bunch of 3rdparty deps, it is packaged separately.
        "src/python/pants/backend/experimental/go",
        "src/python/pants/backend/experimental/go/lint/vet",
        "src/python/pants/backend/experimental/java",
        "src/python/pants/backend/experimental/java/debug_goals",
        "src/python/pants/backend/experimental/java/lint/google_java_format",
        "src/python/pants/backend/experimental/python",
        "src/python/pants/backend/experimental/python/lint/autoflake",
        "src/python/pants/backend/experimental/python/lint/pyupgrade",
        "src/python/pants/backend/experimental/python/packaging/pyoxidizer",
        "src/python/pants/backend/experimental/scala",
        "src/python/pants/backend/experimental/scala/debug_goals",
        "src/python/pants/backend/experimental/scala/lint/scalafmt",
        "src/python/pants/backend/experimental/terraform",
        "src/python/pants/backend/google_cloud_function/python",
        "src/python/pants/backend/plugin_development",
        "src/python/pants/backend/project_info",
        "src/python/pants/backend/python",
        "src/python/pants/backend/python/lint/bandit",
        "src/python/pants/backend/python/lint/black",
        "src/python/pants/backend/python/lint/docformatter",
        "src/python/pants/backend/python/lint/flake8",
        "src/python/pants/backend/python/lint/isort",
        "src/python/pants/backend/python/lint/pylint",
        "src/python/pants/backend/python/lint/yapf",
        "src/python/pants/backend/python/mixed_interpreter_constraints",
        "src/python/pants/backend/python/typecheck/mypy",
        "src/python/pants/backend/shell",
        "src/python/pants/backend/shell/lint/shellcheck",
        "src/python/pants/backend/shell/lint/shfmt",
        "src/python/pants/core",
    ],
)

python_tests(name="tests", timeout=240)
