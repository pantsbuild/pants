# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This contains various smoke tests for out GitHub Actions workflows.
# These aren't meant to be comprehensive, as they can be quite expensive to run. However, they are
# still useful as they can expose bugs before the action is run in "prod".


shell_sources(name="tests")


experimental_test_shell_command(
    name="Test workflow_dispatch dryrun",
    command=f"bash { build_file_dir() / 'smoke_test_all_using_dryrun.sh'}",
    tools=["chmod"],
    execution_dependencies=[
        "//build-support/bin/act:act-at-root",
        "./smoke_test_all_using_dryrun.sh",
        ".github/workflows:workflows",
    ],
    workdir="/",
    timeout=120,
)
