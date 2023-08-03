# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This contains various smoke tests for out GitHub Actions workflows.
# These aren't meant to be comprehensive, as they can be quite expensive to run. However, they are
# still useful as they can expose bugs before the action is run in "prod".

python_tests(
    name="tests",
    dependencies=["//3rdparty/tools/act:act-at-root"],
    timeout=180,
)
