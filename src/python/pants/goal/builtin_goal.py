# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC


class BuiltinGoal(ABC):
    """A goal built-in to pants rather than using the Plugin API."""
