# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Note that targets in this BUILD file have deliberately conflicting interpreter specifications.

python_library(
  name = 'echo_interpreter_version_lib',
  sources = ['echo_interpreter_version.py'],
  # Play with this to test interpreter selection in the pex machinery.
  compatibility = ['CPython>=2.6,<3']
)

python_binary(
  name = 'echo_interpreter_version_2.6',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'interpreter_selection.echo_interpreter_version',
  compatibility = ['CPython>=2.6,<2.7']
)

python_binary(
  name = 'echo_interpreter_version_2.7',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'interpreter_selection.echo_interpreter_version',
  compatibility = ['CPython>=2.7,<3']
)

# Note: Used by tests, but also useful for manual testing.
python_binary(
  name = 'echo_interpreter_version',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'interpreter_selection.echo_interpreter_version',
)

# Note: Used by tests, but also useful for manual testing.
python_binary(
  name = 'deliberately_conficting_compatibility',
  dependencies = [
    ':echo_interpreter_version_lib',
  ],
  entry_point = 'interpreter_selection.echo_interpreter_version',
  compatibility = ['CPython<2.6']
)

python_library(
  name = 'die_lib',
  sources = ['die.py'],
  compatibility = ['CPython>=2.6,<3']
)

python_binary(
  name = 'die',
  dependencies = [
    ':die_lib',
  ],
  entry_point = 'interpreter_selection.die',
)
