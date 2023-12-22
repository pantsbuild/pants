# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(name="tests")

docker_environment(
    name="docker_env_for_testing",
    image="debian:stable-slim",
    mounts=["/etc/passwd:/mount_dir/testfile:ro"],
)

experimental_test_shell_command(
    name="test-docker-environment-bind-mounts",
    tools=["test"],
    command="test -f /mount_dir/testfile",
    environment="docker_for_testing"
)
