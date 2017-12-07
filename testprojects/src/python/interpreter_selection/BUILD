# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note that targets in this BUILD file have deliberately conflicting interpreter specifications.

python_library(
    name = "echo_interpreter_version_lib",
    sources = ["echo_interpreter_version.py"],
    # Play with this to test interpreter selection in the pex machinery.
    compatibility = [
        "CPython>=2.7,<3",
        "CPython>=3.3",
    ],
    dependencies = [],
)

python_binary(
    name = "echo_interpreter_version_3",
    entry_point = "interpreter_selection.echo_interpreter_version",
    compatibility = ["CPython>=3.3"],
    dependencies = [
        ":echo_interpreter_version_lib",
    ],
)

python_binary(
    name = "echo_interpreter_version_2.7",
    entry_point = "interpreter_selection.echo_interpreter_version",
    compatibility = ["CPython>=2.7,<3"],
    dependencies = [
        ":echo_interpreter_version_lib",
    ],
)

# Note: Used by tests, but also useful for manual testing.
python_binary(
    name = "echo_interpreter_version",
    entry_point = "interpreter_selection.echo_interpreter_version",
    dependencies = [
        ":echo_interpreter_version_lib",
    ],
)

# Note: Used by tests, but also useful for manual testing.
python_binary(
    name = "deliberately_conficting_compatibility",
    entry_point = "interpreter_selection.echo_interpreter_version",
    compatibility = ["CPython<2.7"],
    dependencies = [
        ":echo_interpreter_version_lib",
    ],
)

python_library(
    name = "die_lib",
    sources = ["die.py"],
    compatibility = ["CPython>=2.7,<3"],
    dependencies = [],
)

python_binary(
    name = "die",
    entry_point = "interpreter_selection.die",
    dependencies = [
        ":die_lib",
    ],
)
