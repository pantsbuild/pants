# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"])

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(name="files", sources=["BUILD_ROOT", "pants.toml"])

python_test_utils(name="test_utils")

# Used for experimenting with the new Docker support.
docker_environment(
    name="docker_env",
    image="python:3.9",
    python_bootstrap_search_path=["<PATH>"],
)

# See `build-support/reapi-sample-server/README.md` for information on how to use this environment
# for internal testing.
remote_environment(
    name="buildgrid_remote",
    python_bootstrap_search_path=["<PATH>"],
)

files(
    name="all-__init__.py-files",
    sources=[
        "**/__init__.py",
        "!testprojects/**",
        # These are explicit namespace packages
        "!src/python/pants/__init__.py",
        "!src/python/pants/testutil/__init__.py",
    ],
)

# NB: This should be in `lint` when we implement `lint` in https://github.com/pantsbuild/pants/issues/17729
experimental_test_shell_command(
    name="checks-empty-init-files",
    command="""
        NONEMPTY_INITS=$(find . -type f -name "*.py" -size +0);

        if [ -n "$NONEMPTY_INITS" ]; then
            echo "All \\`__init__.py\\` file should be empty, but the following had content:";
            echo "$NONEMPTY_INITS";
            exit 1;
        fi
        exit 0;
    """,
    tools=["echo", "find"],
    execution_dependencies=[":all-__init__.py-files"],
)

docker_environment(
    name="docker_env_for_testing",
    image="debian:stable-slim",
    mounts=["/etc/passwd:/mount_dir/testfile"],
)

experimental_test_shell_command(
    name="test-docker-environment-bind-mounts",
    tools=["test"],
    command="test -f /mount_dir/testfile",
    environment="docker_for_testing"
)
