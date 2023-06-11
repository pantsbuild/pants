# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This contains various smoke tests for out GitHub Actions workflows.
# These aren't meant to be comprehensive, as they can be quite expensive to run. However, they are
# still useful as they can expose bugs before the action is run in "prod".

shell_sources(name="tests")


experimental_test_shell_command(
    name="Test auto-cherry-picker prereqs",
    command=,
    tools=["chmod", "cat"],
    execution_dependencies=[
        "//build-support/bin/act:act-at-root",
        "./smoke_test_auth_cherry_picker.sh",
        ".github/workflows/auto-cherry-picker.yaml",
        "//build-support/bin/cherry_pick/package.json:support_files",
        "//build-support/bin/cherry_pick/package-lock.json:support_files",


experimental_test_shell_command(
    name="Test workflow_dispatch dryrun",
    command="./act workflow_dispatch --dryrun",
    execution_dependencies=[
        "//build-support/bin/act:act-at-root",
        ".github/workflows:workflows",
    ],
    workdir="/",
    timeout=120,
)
