# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.util.meta import decorated_type_checkable


@decorated_type_checkable
def side_effecting(cls):
    """Annotates a class to indicate that it is a side-effecting type, which needs to be handled
    specially with respect to rule caching semantics."""
    return side_effecting.define_instance_of(cls)
