# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC


class NativeGoalRequest(ABC):
    """Represents an implicit or explicit request for help by the user."""
