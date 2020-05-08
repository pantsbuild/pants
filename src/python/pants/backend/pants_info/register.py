# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Information on Pants' internals, such as registered target types and goals."""

from pants.backend.pants_info import list_target_types


def rules():
    return [*list_target_types.rules()]
