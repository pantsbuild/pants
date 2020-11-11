# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.mixed_interpreter_constraints import py_constraints


def rules():
    return py_constraints.rules()
