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
)

# See `build-support/reapi-sample-server/README.md` for information on how to use this environment
# for internal testing.
remote_environment(
    name="buildgrid_remote",
    python_bootstrap_search_path=["<PATH>"],
)


file(
    name = "pybind11",
    source = http_source(
        filename = "pybind11",
        len = 571127,
        sha256 = "1eed57bc6863190e35637290f97a20c81cfe4d9090ac0a24f3bbf08f265eb71d",
        url = "https://github.com/pybind/pybind11/archive/refs/tags/v2.4.3.tar.gz",
    ),
)

experimental_shell_command(
    name="foo",
    dependencies=["//:pybind11"],
    command="echo 'uh oh'",
    tools = ["touch"],
    outputs=["pybind11"]
)

experimental_run_shell_command(
    name="runme",
    command="echo 'run me!'",
    execution_dependencies=["//:foo"],
)
